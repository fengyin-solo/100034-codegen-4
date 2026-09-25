"""车辆调度业务规则。

一次派车的处理口径：
- 值班人勾选多条待出车任务（巡检/消缺）一次提交，系统逐台给出结果；
- 单条任务因司机或车辆时间冲突失败时只标注该条失败原因，成功的照常落单，不整批退回；
- 首选司机/车辆被占用时，按优先级顺延到下一个可用资源，顺延情况写进结果；
- 同一批次内先成功的派车立即占用资源，后续任务也要避让；
- idem_key 命中时原样回放首次结果，重复提交不会生成第二趟派车。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

VEHICLE_MODULE = "vehicle"
DRIVER_MODULE = "driver"
DISPATCH_MODULE = "dispatch"
REQUEST_MODULE = "dispatch_request"

# 巡检/消缺里视为“待出车”的状态，以及候选任务字段与这两个老模块字段的映射。
TASK_SOURCES = {
    "inspection": {
        "label": "巡检",
        "pending_status": "待派发",
        "code": "巡检单号",
        "name": "巡检类型",
        "place": "巡检路线",
    },
    "repair": {
        "label": "消缺",
        "pending_status": "待受理",
        "code": "消缺单号",
        "name": "处理措施",
        "place": "关联缺陷",
    },
}

# 仍占用司机/车辆的派车单状态；已撤回的不占资源，已出车的照样占。
ACTIVE_STATUSES = ["待确认出车", "已出车", "已完成"]
TRIP_STATUSES = ["已出车", "已完成"]
VEHICLE_READY = "可用"
DRIVER_READY = "可派"

STATUS_PENDING = "待确认出车"
STATUS_DEPARTED = "已出车"
STATUS_FINISHED = "已完成"
STATUS_WITHDRAWN = "已撤回"


def _parse_time(value: Any) -> datetime | None:
    """容忍 'YYYY-MM-DD HH:MM' 与 ISO 两种写法；解析不了返回 None。"""
    if not value:
        return None
    text = str(value).strip().replace("/", "-").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _fmt_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def _overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


class DispatchService:
    # ---------- 基础档案与候选任务 ----------

    def list_vehicles(self) -> list[dict[str, Any]]:
        return sorted(store.rows(VEHICLE_MODULE), key=lambda row: (int(row.get("优先级", 99)), int(row.get("id", 0))))

    def list_drivers(self) -> list[dict[str, Any]]:
        return sorted(store.rows(DRIVER_MODULE), key=lambda row: (int(row.get("优先级", 99)), int(row.get("id", 0))))

    def list_dispatch_rows(self) -> list[dict[str, Any]]:
        return store.rows(DISPATCH_MODULE)

    def _task_refs_with_active_dispatch(self) -> set[str]:
        refs: set[str] = set()
        for row in self.list_dispatch_rows():
            if row.get("status") in ACTIVE_STATUSES:
                refs.add(str(row.get("task_ref")))
        return refs

    def list_candidates(self) -> list[dict[str, Any]]:
        """从巡检、消缺老列表里只读挑出待出车任务，不改动老模块任何数据。"""
        blocked = self._task_refs_with_active_dispatch()
        candidates: list[dict[str, Any]] = []
        for module, meta in TASK_SOURCES.items():
            for row in store.rows(module):
                if row.get("status") != meta["pending_status"]:
                    continue
                task_ref = f"{module}:{row['id']}"
                candidates.append({
                    "task_ref": task_ref,
                    "任务类型": meta["label"],
                    "任务单号": row.get(meta["code"]),
                    "任务名称": row.get(meta["name"]),
                    "目的地": row.get(meta["place"]),
                    "原始状态": row.get("status"),
                    "可派车": task_ref not in blocked,
                    "占用说明": "" if task_ref not in blocked else "已有进行中的派车单",
                })
        return candidates

    def resources(self) -> dict[str, Any]:
        return {
            "vehicles": self.list_vehicles(),
            "drivers": self.list_drivers(),
            "candidates": self.list_candidates(),
        }

    def _find_candidate(self, task_ref: str) -> dict[str, Any] | None:
        for candidate in self.list_candidates():
            if candidate["task_ref"] == task_ref:
                return candidate
        return None

    # ---------- 派车单查询 ----------

    def list_orders(
        self,
        *,
        batch_id: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.list_dispatch_rows()
        if batch_id:
            rows = [row for row in rows if row.get("批次号") == batch_id]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("任务单号", ""))
                or keyword in str(row.get("车牌", ""))
                or keyword in str(row.get("司机", ""))
                or keyword in str(row.get("目的地", ""))
            ]
        return sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)

    def list_trips(self, *, driver: str | None = None, batch_id: str | None = None) -> list[dict[str, Any]]:
        """行车记录与派车结果同源：就是状态走到已出车/已完成的派车单，不另建数据。"""
        rows = [row for row in self.list_orders(batch_id=batch_id) if row.get("status") in TRIP_STATUSES]
        if driver:
            rows = [row for row in rows if row.get("司机") == driver]
        return rows

    # ---------- 批量派车 ----------

    def _occupancy(self, kind: str, resource_id: int, start: datetime, end: datetime) -> dict[str, Any] | None:
        """返回与给定时段重叠的占用派车单；本批次刚创建的单子也在表里，一并参与判断。"""
        field = "车辆id" if kind == "vehicle" else "司机id"
        for row in self.list_dispatch_rows():
            if row.get("status") not in ACTIVE_STATUSES:
                continue
            if int(row.get(field, 0)) != resource_id:
                continue
            row_start = _parse_time(row.get("开始时间"))
            row_end = _parse_time(row.get("结束时间"))
            if row_start and row_end and _overlap(start, end, row_start, row_end):
                return row
        return None

    def _conflict_text(self, kind: str, occupier: dict[str, Any]) -> str:
        who = "车辆" if kind == "vehicle" else "司机"
        name = occupier.get("车牌") if kind == "vehicle" else occupier.get("司机")
        return (
            f"{who}{name}在 {occupier.get('开始时间')}~{occupier.get('结束时间')} "
            f"已承担{occupier.get('任务类型')}任务{occupier.get('任务单号')}（批次 {occupier.get('批次号')}）"
        )

    def _choose_resource(
        self,
        kind: str,
        preferred_id: int | None,
        start: datetime,
        end: datetime,
    ) -> tuple[dict[str, Any] | None, bool, list[str]]:
        """按“首选 → 优先级顺延”挑资源，返回(资源, 是否顺延, 过程说明)；挑不到时资源为 None。"""
        who = "车辆" if kind == "vehicle" else "司机"
        pool = self.list_vehicles() if kind == "vehicle" else self.list_drivers()
        ready_status = VEHICLE_READY if kind == "vehicle" else DRIVER_READY
        status_field = "车辆状态" if kind == "vehicle" else "司机状态"
        name_field = "车牌" if kind == "vehicle" else "司机姓名"
        notes: list[str] = []

        if preferred_id is not None:
            preferred = next((row for row in pool if int(row.get("id", 0)) == preferred_id), None)
            if preferred is None:
                notes.append(f"首选{who}不存在，改按优先级顺延")
            elif preferred.get(status_field) != ready_status:
                notes.append(f"首选{who}{preferred.get(name_field)}当前状态为「{preferred.get(status_field)}」，不可派车，按优先级顺延")
            else:
                occupier = self._occupancy(kind, preferred_id, start, end)
                if occupier is not None:
                    notes.append(f"首选{who}{preferred.get(name_field)}时间冲突：{self._conflict_text(kind, occupier)}，按优先级顺延")
                else:
                    return preferred, False, notes

        for candidate in pool:
            if candidate.get(status_field) != ready_status:
                continue
            occupier = self._occupancy(kind, int(candidate["id"]), start, end)
            if occupier is not None:
                continue
            return candidate, preferred_id is not None, notes

        # 所有可派资源都不可用：把被占用的情况写清楚，避免只报一句“无资源”。
        blocked = []
        for candidate in pool:
            if candidate.get(status_field) != ready_status:
                blocked.append(f"{candidate.get(name_field)}（{candidate.get(status_field)}）")
                continue
            occupier = self._occupancy(kind, int(candidate["id"]), start, end)
            if occupier is not None:
                blocked.append(self._conflict_text(kind, occupier))
        notes.append(f"无可用{who}：{ '；'.join(blocked) if blocked else '档案为空'}")
        return None, preferred_id is not None, notes

    def _next_batch_id(self) -> str:
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"DISP-{today}-"
        seq = 0
        for row in self.list_dispatch_rows():
            text = str(row.get("批次号", ""))
            if text.startswith(prefix):
                try:
                    seq = max(seq, int(text.rsplit("-", 1)[-1]))
                except ValueError:
                    continue
        return f"{prefix}{seq + 1:02d}"

    def create_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        idem_key = str(payload.get("idem_key") or "").strip()
        if not idem_key:
            raise ValueError("缺少幂等键 idem_key，无法防止重复提交")

        # 重复提交：原样回放首次的派车结果，不再落任何新单。
        for cached in store.rows(REQUEST_MODULE):
            if cached.get("idem_key") == idem_key:
                result = dict(cached["result"])
                result["replayed"] = True
                return result

        raw_items = payload.get("items") or []
        batch_id = self._next_batch_id()
        results: list[dict[str, Any]] = []
        seen_refs: dict[str, int] = {}

        for index, item in enumerate(raw_items, start=1):
            task_ref = str(item.get("task_ref") or "").strip()
            base = {
                "序号": index,
                "task_ref": task_ref,
                "批次号": batch_id,
                "开始时间": str(item.get("start_time") or ""),
                "结束时间": str(item.get("end_time") or ""),
            }
            candidate = self._find_candidate(task_ref)

            failures: list[str] = []
            if not task_ref:
                failures.append("未指定作业任务")
            elif candidate is None:
                failures.append(f"任务 {task_ref} 不在待出车列表（不存在或已不在待处理状态）")
            elif not candidate["可派车"]:
                active = next(
                    (row for row in self.list_dispatch_rows()
                     if row.get("task_ref") == task_ref and row.get("status") in ACTIVE_STATUSES),
                    None,
                )
                if active is not None:
                    failures.append(
                        f"该任务已有进行中的派车单 {active.get('批次号')}（{active.get('车牌')}/司机{active.get('司机')}），不能重复派车"
                    )
                else:
                    failures.append("该任务已有进行中的派车单，不能重复派车")
            if task_ref in seen_refs:
                failures.append(f"与本批次第 {seen_refs[task_ref]} 项是同一任务，一次派车不能重复")

            start = _parse_time(item.get("start_time"))
            end = _parse_time(item.get("end_time"))
            if start is None or end is None:
                failures.append("用车时间填写不完整或格式不正确（应为 YYYY-MM-DD HH:MM）")
            elif end <= start:
                failures.append("用车结束时间必须晚于开始时间")

            if failures:
                results.append({
                    **base,
                    "ok": False,
                    "任务类型": candidate["任务类型"] if candidate else "",
                    "任务单号": candidate["任务单号"] if candidate else "",
                    "任务名称": candidate["任务名称"] if candidate else "",
                    "目的地": item.get("destination") or (candidate["目的地"] if candidate else ""),
                    "车牌": None,
                    "司机": None,
                    "顺延车辆": False,
                    "顺延司机": False,
                    "说明": "",
                    "失败原因": "；".join(failures),
                    "派车单id": None,
                })
                continue

            assert candidate is not None and start is not None and end is not None
            vehicle_id = item.get("vehicle_id")
            driver_id = item.get("driver_id")
            vehicle_id = int(vehicle_id) if vehicle_id not in (None, "") else None
            driver_id = int(driver_id) if driver_id not in (None, "") else None

            vehicle, vehicle_deferred, vehicle_notes = self._choose_resource("vehicle", vehicle_id, start, end)
            driver, driver_deferred, driver_notes = self._choose_resource("driver", driver_id, start, end)
            notes = vehicle_notes + driver_notes

            if vehicle is None or driver is None:
                # 单条失败：只标注这一条，前面已成功的派车单保留，不整批退回。
                results.append({
                    **base,
                    "ok": False,
                    "任务类型": candidate["任务类型"],
                    "任务单号": candidate["任务单号"],
                    "任务名称": candidate["任务名称"],
                    "目的地": item.get("destination") or candidate["目的地"],
                    "车牌": vehicle.get("车牌") if vehicle else None,
                    "司机": driver.get("司机姓名") if driver else None,
                    "顺延车辆": vehicle_deferred,
                    "顺延司机": driver_deferred,
                    "说明": "",
                    "失败原因": "；".join(notes),
                    "派车单id": None,
                })
                continue

            rows = self.list_dispatch_rows()
            order = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "批次号": batch_id,
                "task_ref": task_ref,
                "任务类型": candidate["任务类型"],
                "任务单号": candidate["任务单号"],
                "任务名称": candidate["任务名称"],
                "目的地": item.get("destination") or candidate["目的地"],
                "开始时间": _fmt_time(start),
                "结束时间": _fmt_time(end),
                "车辆id": int(vehicle["id"]),
                "车牌": vehicle.get("车牌"),
                "司机id": int(driver["id"]),
                "司机": driver.get("司机姓名"),
                "联系电话": driver.get("联系电话"),
                "顺延车辆": vehicle_deferred,
                "顺延司机": driver_deferred,
                "说明": "；".join(notes),
                "status": STATUS_PENDING,
                "pending": True,
                "abnormal": False,
                "confirmed_at": None,
            }
            rows.append(order)
            seen_refs[task_ref] = index

            results.append({
                **base,
                "ok": True,
                "任务类型": order["任务类型"],
                "任务单号": order["任务单号"],
                "任务名称": order["任务名称"],
                "目的地": order["目的地"],
                "开始时间": order["开始时间"],
                "结束时间": order["结束时间"],
                "车牌": order["车牌"],
                "司机": order["司机"],
                "顺延车辆": vehicle_deferred,
                "顺延司机": driver_deferred,
                "说明": order["说明"],
                "失败原因": None,
                "派车单id": order["id"],
            })

        success = sum(1 for row in results if row["ok"])
        result = {
            "ok": True,
            "批次号": batch_id,
            "全部成功": success == len(results) and bool(results),
            "成功数": success,
            "失败数": len(results) - success,
            "items": results,
            "replayed": False,
            "message": (
                f"批次 {batch_id} 派车完成：成功 {success} 台，失败 {len(results) - success} 台"
                if results
                else "本次没有提交任何待派车任务"
            ),
        }
        store.rows(REQUEST_MODULE).append({"idem_key": idem_key, "批次号": batch_id, "result": result})
        return result

    # ---------- 确认出车 / 撤回 ----------

    def confirm(self, order_id: int, driver_name: str | None = None) -> tuple[dict[str, Any] | None, str]:
        """司机确认出车：待确认 -> 已出车；重复确认只回放当前状态，不产生第二条记录。"""
        order = store.find(DISPATCH_MODULE, order_id)
        if order is None:
            return None, f"派车单 {order_id} 不存在"
        if driver_name and order.get("司机") and driver_name != order.get("司机"):
            return None, f"该派车单指派司机为{order.get('司机')}，司机账号不匹配，不能代确认"
        if order["status"] == STATUS_DEPARTED:
            return order, f"派车单 {order_id} 已确认出车，请勿重复操作"
        if order["status"] == STATUS_FINISHED:
            return order, f"派车单 {order_id} 已完成"
        if order["status"] == STATUS_WITHDRAWN:
            return None, "派车单已撤回，不能确认出车"
        order["status"] = STATUS_DEPARTED
        order["pending"] = False
        order["confirmed_at"] = _fmt_time(datetime.now())
        return order, f"派车单 {order_id} 已确认出车，行车记录已生成"

    def withdraw(self, *, ids: list[int] | None = None, batch_id: str | None = None) -> list[dict[str, Any]]:
        """撤回只改状态、不删行：已出车的单子拦下并保留行车记录，也不会新增任何行。"""
        rows = self.list_dispatch_rows()
        if batch_id:
            targets = [row for row in rows if row.get("批次号") == batch_id]
        elif ids:
            targets = [row for row in rows if int(row.get("id", 0)) in set(ids)]
        else:
            return []

        results: list[dict[str, Any]] = []
        for order in targets:
            order_id = int(order["id"])
            if order["status"] == STATUS_WITHDRAWN:
                results.append({"id": order_id, "ok": True, "status": order["status"], "message": "派车单已是撤回状态"})
            elif order["status"] in TRIP_STATUSES:
                results.append({
                    "id": order_id,
                    "ok": False,
                    "status": order["status"],
                    "message": f"派车单 {order_id}（{order.get('任务单号')}）已出车，不能撤回，行车记录保留",
                })
            else:
                order["status"] = STATUS_WITHDRAWN
                order["pending"] = False
                results.append({"id": order_id, "ok": True, "status": order["status"], "message": f"派车单 {order_id} 已撤回，资源占用已释放"})
        return results


dispatch_service = DispatchService()
