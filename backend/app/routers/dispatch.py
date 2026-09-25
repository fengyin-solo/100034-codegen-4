"""车辆调度接口：候选任务、批量派车、确认出车、撤回派车与行车记录。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import PageResult
from app.services.dispatch import dispatch_service

router = APIRouter(prefix="/api/dispatch", tags=["车辆调度"])


class DispatchItem(BaseModel):
    task_ref: str
    start_time: str
    end_time: str
    destination: str | None = None
    vehicle_id: int | None = None
    driver_id: int | None = None


class DispatchBatchPayload(BaseModel):
    items: list[DispatchItem] = Field(default_factory=list)
    idem_key: str = ""


class ConfirmPayload(BaseModel):
    driver_name: str | None = None


class WithdrawPayload(BaseModel):
    ids: list[int] = Field(default_factory=list)
    batch_id: str | None = None


def _page(rows: list[dict[str, Any]], page: int, size: int) -> PageResult[dict]:
    total = len(rows)
    start = max(page - 1, 0) * size
    return PageResult(items=rows[start:start + size], total=total, page=page, size=size)


@router.get("/resources")
def resources() -> dict[str, Any]:
    """派车弹窗初始化数据：车辆、司机按优先级排好，候选任务只读来自巡检/消缺列表。"""
    return dispatch_service.resources()


@router.get("/candidates")
def candidates() -> dict[str, Any]:
    """待出车作业任务：巡检待派发 + 消缺待受理，已有进行中派车单的会被标不可选。"""
    items = dispatch_service.list_candidates()
    return {"items": items, "total": len(items)}


@router.get("/orders", response_model=PageResult[dict])
def list_orders(
    batch_id: str | None = Query(default=None, description="按批次号过滤"),
    status: str | None = Query(default=None, description="待确认出车、已出车、已完成、已撤回"),
    keyword: str | None = Query(default=None, description="按任务单号/车牌/司机/目的地检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """派车结果列表，可按批次、状态、关键字筛选。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    rows = dispatch_service.list_orders(batch_id=batch_id, status=status, keyword=keyword)
    return _page(rows, page, size)


@router.get("/trips", response_model=PageResult[dict])
def list_trips(
    driver: str | None = Query(default=None, description="按司机姓名过滤，司机端只看自己的行车记录"),
    batch_id: str | None = Query(default=None),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """行车记录与派车单同源：只列出已出车/已完成的派车单。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    rows = dispatch_service.list_trips(driver=driver, batch_id=batch_id)
    return _page(rows, page, size)


@router.post("/batches")
def create_batch(payload: DispatchBatchPayload) -> dict[str, Any]:
    """一次提交多条待出车任务，逐台返回派车结果；冲突条目标注原因但不整批退回。

    幂等：同一 idem_key 重复提交时回放首次结果，不会再生成派车单。
    """
    try:
        return dispatch_service.create_batch(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/orders/{order_id}/confirm")
def confirm_order(order_id: int, payload: ConfirmPayload) -> dict[str, Any]:
    """司机确认出车，确认后该单进入行车记录；重复确认不会多出记录。"""
    entry, message = dispatch_service.confirm(order_id, payload.driver_name)
    if entry is None:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "entry": entry}


@router.post("/withdraw")
def withdraw_orders(payload: WithdrawPayload) -> dict[str, Any]:
    """撤回未出车的派车单；已出车的逐条拦下并保留，撤回不删行、不加行。"""
    if not payload.ids and not payload.batch_id:
        raise HTTPException(status_code=400, detail="请指定要撤回的派车单（ids 或 batch_id）")
    results = dispatch_service.withdraw(ids=payload.ids or None, batch_id=payload.batch_id)
    blocked = [row for row in results if not row["ok"]]
    return {
        "ok": not blocked,
        "message": (
            f"撤回完成：{sum(1 for row in results if row['ok'])} 条成功，{len(blocked)} 条因已出车保留"
            if results
            else "没有匹配到可撤回的派车单"
        ),
        "items": results,
    }
