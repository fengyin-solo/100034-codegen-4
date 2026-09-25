"""车辆调度业务规则：批量派车、按优先级顺延、行车记录一致性都收在这里。

设计要点：
- 待出车任务池来自巡检、消缺两个模块的在办单据，派车不反向改动原模块，老列表照旧；
- 批量派车逐台结算：资源不可用只失败当前这一台并标出原因，整批不被退回；
- 同批次内按优先级排队，高优先级先占位，时间冲突的单子顺延到下一个空档；
- batch_id 是幂等键：网络重试、双击重复提交都返回首次结果，不会生成第二趟派车；
- 行车记录由「确认出车」生成，一张派车单只对应一条记录；已出车的派车单不能撤回，
  撤回动作不删任何行，已出车那条和它的行车记录都原样保留。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "dispatch"
TRIP_MODULE = "trip"
BATCH_MODULE = "dispatch_batch"

TASK_SOURCES = {
    "inspection": {"label": "巡检任务", "active": ("待派发", "巡检中"), "code": "巡检单号", "dest": "巡检路线", "time": "开始时间"},
    "repair": {"label": "消缺处理", "active": ("待受理", "处理中"), "code": "消缺单号", "dest": "关联缺陷", "time": "完成时间"},
}
ACTIVE_DISPATCH_STATUSES = ("待出车", "已出车")
PRIORITY_ORDER = {"高": 0, "中": 1, "低": 2}
DEFER_LIMIT = 6
TIME_FMT = "%Y-%m-%d %H:%M"
STATUS_ORDER = ["待出车", "已出车", "已完成", "已撤回"]


def _now() -> str:
    return datetime.now().strftime(TIME_FMT)


def _parse(text: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text or "").strip())
    except ValueError:
        return None


def _fmt(moment: datetime) -> str:
    return moment.strftime(TIME_FMT)


def _task_key(module: str, task_id: Any) -> str:
    return f"{module}:{task_id}"


class DispatchService:
    # ---------- 待出车任务池 ----------
    def list_tasks(self) -> list[dict[str, Any]]:
        busy = self._active_task_keys()
        tasks: list[dict[str, Any]] = []
        for module, meta in TASK_SOURCES.items():
            for row in store.rows(module):
                if row.get("status") not in meta["active"]:
                    continue
                key = _task_key(module, row.get("id"))
                if key in busy:
                    continue
                tasks.append({
                    "task_key": key,
                    "任务来源": meta["label"],
                    "任务单号": row.get(meta["code"]),
                    "目的地": row.get(meta["dest"]),
                    "建议出车时间": row.get(meta["time"]),
                    "任务状态": row.get("status"),
                })
        return tasks

    def list_resources(self) -> dict[str, Any]:
        """车辆与司机清单，顺手标出各自被占用的时间窗口，给派车弹窗做提示。"""
        vehicles = [dict(row) for row in store.rows("vehicle")]
        drivers = [dict(row) for row in store.rows("driver")]
        for row in (*vehicles, *drivers):
            row["占用窗口"] = []
        for entry in store.rows(MODULE):
            if entry.get("status") not in ACTIVE_DISPATCH_STATUSES:
                continue
            window = f"{entry.get('计划出车时间')}~{entry.get('计划返回时间')}"
            for vehicle in vehicles:
                if vehicle.get("id") == entry.get("车辆ID"):
                    vehicle["占用窗口"].append(window)
            for driver in drivers:
                if driver.get("id") == entry.get("司机ID"):
                    driver["占用窗口"].append(window)
        return {"vehicles": vehicles, "drivers": drivers}

    # ---------- 派车单与行车记录列表 ----------
    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("派车单号", ""))
                or keyword in str(row.get("任务单号", ""))
                or keyword in str(row.get("司机", ""))
                or keyword in str(row.get("车牌号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def list_trips(
        self,
        *,
        driver: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(TRIP_MODULE)
        if driver:
            rows = [row for row in rows if driver in str(row.get("司机", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    # ---------- 批量派车 ----------
    def submit_batch(
        self,
        batch_id: str,
        items: list[dict[str, Any]],
    ) -> tuple[dict[str, int] | None, str, list[dict[str, Any]]]:
        batch_id = (batch_id or "").strip()
        if not items:
            return None, "未选择需要派车的作业任务", []
        if batch_id:
            for batch in store.rows(BATCH_MODULE):
                if batch.get("batch_id") == batch_id:
                    summary = batch["summary"]
                    message = f"批次 {batch_id} 已提交过，重复提交不会生成新派车单（原结果：{self._summary_text(summary)}）"
                    return summary, message, batch["results"]

        prepared: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for raw in items:
            item, error = self._prepare_item(raw, seen_keys)
            if error is not None:
                results.append(error)
            elif item is not None:
                prepared.append(item)

        # 同批次按优先级排队：高优先级先占位，冲突的低优先级往后顺延
        prepared.sort(key=lambda row: (PRIORITY_ORDER[row["priority"]], row["start"]))
        for item in prepared:
            results.append(self._settle_one(item, batch_id))

        summary = {
            "total": len(items),
            "success": sum(1 for row in results if row["result"] == "成功"),
            "deferred": sum(1 for row in results if row["result"] == "已顺延"),
            "failed": sum(1 for row in results if row["result"] == "失败"),
        }
        message = f"共 {summary['total']} 台：{self._summary_text(summary)}"
        if batch_id:
            store.rows(BATCH_MODULE).append({
                "batch_id": batch_id,
                "summary": summary,
                "results": results,
                "created_at": _now(),
            })
        return summary, message, results

    @staticmethod
    def _summary_text(summary: dict[str, int]) -> str:
        return f"成功 {summary['success']} 台 · 顺延 {summary['deferred']} 台 · 失败 {summary['failed']} 台"

    def _prepare_item(
        self,
        raw: dict[str, Any],
        seen_keys: set[str],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """硬校验：任务、车辆、司机、时间任何一项不过关，只失败这一台。"""
        key = str(raw.get("task_key") or "").strip()
        base = {"task_key": key, "任务单号": "", "车牌号": "", "司机": "", "计划出车时间": "", "计划返回时间": "", "派车单号": ""}

        def fail(reason: str, **extra: Any) -> dict[str, Any]:
            return {**base, "result": "失败", "reason": reason, **extra}

        if not key:
            return None, fail("缺少任务标识，无法派车")
        if key in seen_keys:
            return None, fail("同一任务在同一批次里重复提交")
        seen_keys.add(key)

        module, _, task_id_text = key.partition(":")
        meta = TASK_SOURCES.get(module)
        task_row = store.find(module, int(task_id_text)) if meta and task_id_text.isdigit() else None
        if meta is None or task_row is None:
            return None, fail("作业任务不存在，请刷新待出车列表")
        base["任务单号"] = str(task_row.get(meta["code"], ""))
        if task_row.get("status") not in meta["active"]:
            return None, fail(f"任务当前状态为{task_row.get('status')}，不在待出车范围")
        occupying = self._task_dispatch(key)
        if occupying is not None:
            return None, fail(f"任务已存在进行中的派车单 {occupying.get('派车单号')}，不能重复派车")

        vehicle_id = int(raw.get("vehicle_id") or 0)
        vehicle = store.find("vehicle", vehicle_id)
        if vehicle is None:
            return None, fail("未找到所选车辆，请重新选择")
        base["车牌号"] = str(vehicle.get("车牌号", ""))
        if vehicle.get("status") != "可用":
            return None, fail(f"车辆{vehicle.get('车牌号')}{vehicle.get('status')}，暂不可派", 车牌号=base["车牌号"])

        driver_id = int(raw.get("driver_id") or 0)
        driver = store.find("driver", driver_id)
        if driver is None:
            return None, fail("未找到所选司机，请重新选择", 车牌号=base["车牌号"])
        base["司机"] = str(driver.get("司机姓名", ""))
        if driver.get("status") != "在岗":
            return None, fail(f"司机{driver.get('司机姓名')}{driver.get('status')}，暂不可派", 车牌号=base["车牌号"], 司机=base["司机"])

        start = _parse(raw.get("start"))
        end = _parse(raw.get("end"))
        if start is None or end is None:
            return None, fail("出车或返回时间格式不正确", 车牌号=base["车牌号"], 司机=base["司机"])
        if end <= start:
            return None, fail("计划返回时间必须晚于计划出车时间", 车牌号=base["车牌号"], 司机=base["司机"])

        priority = str(raw.get("priority") or "中")
        if priority not in PRIORITY_ORDER:
            priority = "中"
        item = {
            "task_key": key,
            "module": module,
            "task_id": task_row.get("id"),
            "任务单号": base["任务单号"],
            "任务来源": meta["label"],
            "目的地": str(task_row.get(meta["dest"], "")),
            "vehicle": vehicle,
            "driver": driver,
            "start": start,
            "end": end,
            "priority": priority,
        }
        return item, None

    def _settle_one(self, item: dict[str, Any], batch_id: str) -> dict[str, Any]:
        """给一台车找时间窗：冲突就按优先级顺延，顺延不下才判失败。"""
        vehicle = item["vehicle"]
        driver = item["driver"]
        start, end = item["start"], item["end"]
        duration = end - start
        base = {
            "task_key": item["task_key"],
            "任务单号": item["任务单号"],
            "车牌号": vehicle.get("车牌号", ""),
            "司机": driver.get("司机姓名", ""),
        }

        hops = 0
        conflict = self._find_conflict(vehicle["id"], driver["id"], start, end)
        first_conflict = conflict
        while conflict is not None and hops < DEFER_LIMIT:
            hops += 1
            conflict_end = _parse(conflict.get("计划返回时间"))
            if conflict_end is None:
                break
            start = conflict_end
            end = start + duration
            conflict = self._find_conflict(vehicle["id"], driver["id"], start, end)

        if conflict is not None:
            reason = f"{self._conflict_text(conflict, vehicle['id'], driver['id'])}，顺延 {DEFER_LIMIT} 次后仍冲突，请改派其他车辆或司机"
            return {**base, "result": "失败", "reason": reason, "计划出车时间": "", "计划返回时间": "", "派车单号": ""}

        entry = self._create_dispatch(item, start, end, hops, batch_id)
        result = {
            **base,
            "计划出车时间": entry["计划出车时间"],
            "计划返回时间": entry["计划返回时间"],
            "派车单号": entry["派车单号"],
        }
        if hops:
            occupied = self._conflict_text(first_conflict, vehicle["id"], driver["id"]) if first_conflict else "时间窗冲突"
            result["result"] = "已顺延"
            result["reason"] = f"{occupied}，已按优先级顺延至 {entry['计划出车时间']}~{entry['计划返回时间']}"
        else:
            result["result"] = "成功"
            result["reason"] = ""
        return result

    def _create_dispatch(
        self,
        item: dict[str, Any],
        start: datetime,
        end: datetime,
        hops: int,
        batch_id: str,
    ) -> dict[str, Any]:
        rows = store.rows(MODULE)
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry = {
            "id": next_id,
            "派车单号": f"DISP-{next_id:04d}",
            "批次号": batch_id or "—",
            "任务模块": item["module"],
            "任务来源": item["任务来源"],
            "任务ID": item["task_id"],
            "任务单号": item["任务单号"],
            "目的地": item["目的地"],
            "司机ID": item["driver"]["id"],
            "司机": item["driver"].get("司机姓名", ""),
            "车辆ID": item["vehicle"]["id"],
            "车牌号": item["vehicle"].get("车牌号", ""),
            "计划出车时间": _fmt(start),
            "计划返回时间": _fmt(end),
            "原始出车时间": _fmt(item["start"]) if hops else "",
            "优先级": item["priority"],
            "顺延次数": hops,
            "失败原因": "",
            "创建时间": _now(),
            "status": "待出车",
            "pending": True,
            "abnormal": False,
        }
        rows.append(entry)
        return entry

    # ---------- 派车单动作 ----------
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"派车单 {entry_id} 不存在或已归档"
        if action == "确认出车":
            if entry.get("status") != "待出车":
                return None, f"派车单当前状态为{entry.get('status')}，不能确认出车"
            entry["status"] = "已出车"
            self._ensure_trip(entry)
            return entry, "司机已确认出车，行车记录已生成"
        if action == "确认归队":
            if entry.get("status") != "已出车":
                return None, f"派车单当前状态为{entry.get('status')}，不能确认归队"
            entry["status"] = "已完成"
            entry["pending"] = False
            trip = self._find_trip(entry.get("派车单号"))
            if trip is not None and trip.get("status") == "行程中":
                trip["status"] = "已归队"
                trip["返回时间"] = _now()
                trip["pending"] = False
            return entry, "车辆已归队，行车记录已更新"
        if action == "撤回派车":
            if entry.get("status") == "已出车":
                return None, "派车单已出车，行车记录需保留，不能撤回"
            if entry.get("status") != "待出车":
                return None, f"派车单当前状态为{entry.get('status')}，不能撤回"
            entry["status"] = "已撤回"
            entry["pending"] = False
            entry["abnormal"] = True
            return entry, "派车单已撤回，车辆与司机已释放，任务回到待出车列表"
        return None, f"动作「{action}」不属于车辆调度可执行范围"

    # ---------- 内部工具 ----------
    def _active_task_keys(self) -> set[str]:
        keys: set[str] = set()
        for row in store.rows(MODULE):
            if row.get("status") in ACTIVE_DISPATCH_STATUSES:
                keys.add(_task_key(str(row.get("任务模块")), row.get("任务ID")))
        return keys

    def _task_dispatch(self, key: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if row.get("status") in ACTIVE_DISPATCH_STATUSES and _task_key(str(row.get("任务模块")), row.get("任务ID")) == key:
                return row
        return None

    def _find_conflict(
        self,
        vehicle_id: int,
        driver_id: int,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if row.get("status") not in ACTIVE_DISPATCH_STATUSES:
                continue
            if row.get("车辆ID") != vehicle_id and row.get("司机ID") != driver_id:
                continue
            busy_start = _parse(row.get("计划出车时间"))
            busy_end = _parse(row.get("计划返回时间"))
            if busy_start and busy_end and start < busy_end and busy_start < end:
                return row
        return None

    @staticmethod
    def _conflict_text(conflict: dict[str, Any], vehicle_id: int, driver_id: int) -> str:
        parts: list[str] = []
        if conflict.get("车辆ID") == vehicle_id:
            parts.append(f"车辆{conflict.get('车牌号')}")
        if conflict.get("司机ID") == driver_id:
            parts.append(f"司机{conflict.get('司机')}")
        who = "、".join(parts) or "所选资源"
        return f"{who}在 {conflict.get('计划出车时间')}~{conflict.get('计划返回时间')} 已被派车单{conflict.get('派车单号')}占用"

    def _find_trip(self, dispatch_code: Any) -> dict[str, Any] | None:
        for row in store.rows(TRIP_MODULE):
            if row.get("派车单号") == dispatch_code:
                return row
        return None

    def _ensure_trip(self, entry: dict[str, Any]) -> dict[str, Any]:
        """一张派车单只生成一条行车记录，重复确认不会多出第二行。"""
        existing = self._find_trip(entry.get("派车单号"))
        if existing is not None:
            return existing
        rows = store.rows(TRIP_MODULE)
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        trip = {
            "id": next_id,
            "记录编号": f"TRIP-{next_id:04d}",
            "派车单号": entry.get("派车单号", ""),
            "任务单号": entry.get("任务单号", ""),
            "目的地": entry.get("目的地", ""),
            "司机ID": entry.get("司机ID"),
            "司机": entry.get("司机", ""),
            "车辆ID": entry.get("车辆ID"),
            "车牌号": entry.get("车牌号", ""),
            "出车时间": _now(),
            "返回时间": "",
            "status": "行程中",
            "pending": True,
            "abnormal": False,
        }
        rows.append(trip)
        return trip
