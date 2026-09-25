"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import station as router_station
from app.routers import array as router_array
from app.routers import inverter as router_inverter
from app.routers import combiner as router_combiner
from app.routers import stringmon as router_stringmon
from app.routers import irradiance as router_irradiance
from app.routers import cleaning as router_cleaning
from app.routers import inspection as router_inspection
from app.routers import defect as router_defect
from app.routers import repair as router_repair
from app.routers import sparepart as router_sparepart
from app.routers import generation as router_generation
from app.routers import curtail as router_curtail
from app.routers import alarm as router_alarm
from app.routers import permit as router_permit
from app.routers import contractor as router_contractor
from app.routers import training as router_training
from app.routers import settlement as router_settlement
from app.routers import dispatch as router_dispatch

ROUTERS = [router_station, router_array, router_inverter, router_combiner, router_stringmon, router_irradiance, router_cleaning, router_inspection, router_defect, router_repair, router_sparepart, router_generation, router_curtail, router_alarm, router_permit, router_contractor, router_training, router_settlement, router_dispatch]
