"""车辆调度接口：待出车任务池、批量派车、派车单流转与行车记录。

注意路由顺序：/tasks、/resources、/batch、/trips 这些固定路径必须写在 /{entry_id}
前面，否则 "tasks" 会被当成 entry_id 去匹配，直接 422。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, DispatchBatchPayload, DispatchBatchResult, EntryPayload, PageResult
from app.services.dispatch import DispatchService

router = APIRouter(prefix="/api/dispatch", tags=["车辆调度"])

service = DispatchService()

STATUSES = ["待出车", "已出车", "已完成", "已撤回"]


@router.get("/tasks")
def list_tasks() -> dict[str, object]:
    """待出车作业任务池：巡检、消缺两个模块的在办单据，扣掉已有进行中派车单的任务。"""
    return {"items": service.list_tasks()}


@router.get("/resources")
def list_resources() -> dict[str, object]:
    """车辆与司机清单，带各自被占用的时间窗口，供派车弹窗选择。"""
    return service.list_resources()


@router.post("/batch", response_model=DispatchBatchResult)
def submit_batch(payload: DispatchBatchPayload) -> DispatchBatchResult:
    """一次提交多台派车：逐台结算，失败单台标注原因，整批不退回；batch_id 相同视为重复提交，直接返回首次结果。"""
    items = [item.model_dump() for item in payload.items]
    summary, message, results = service.submit_batch(payload.batch_id, items)
    if summary is None:
        return DispatchBatchResult(ok=False, message=message, batch_id=payload.batch_id)
    return DispatchBatchResult(ok=True, message=message, batch_id=payload.batch_id, summary=summary, results=results)


@router.get("/trips", response_model=PageResult[dict])
def list_trips(
    driver: str | None = Query(default=None, description="按司机姓名检索行车记录"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """行车记录：司机确认出车后在这里看到自己的每一趟行程。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_trips(driver=driver, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按派车单号、任务单号、司机、车牌检索"),
    status: str | None = Query(default=None, description="待出车、已出车、已完成、已撤回"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """派车单列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条派车单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"派车单 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条派车单执行确认出车、确认归队、撤回派车；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
