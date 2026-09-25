<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">光伏电站智能运维平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向光伏电站并网、方阵逆变器监测、组件清洗巡检、消缺处理与发电量结算的一体化运维后台。</span>
        <span class="head-user">当前值班：{{ store.operator }} · {{ store.shiftLabel }}</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()

const navItems = [{ label: "运营概览", path: "/" }, { label: "光伏电站", path: "/station" }, { label: "光伏方阵", path: "/array" }, { label: "逆变器管理", path: "/inverter" }, { label: "汇流箱管理", path: "/combiner" }, { label: "组串监测", path: "/stringmon" }, { label: "辐照监测", path: "/irradiance" }, { label: "组件清洗", path: "/cleaning" }, { label: "巡检任务", path: "/inspection" }, { label: "缺陷登记", path: "/defect" }, { label: "消缺处理", path: "/repair" }, { label: "备件领用", path: "/sparepart" }, { label: "发电量核算", path: "/generation" }, { label: "限电记录", path: "/curtail" }, { label: "告警中心", path: "/alarm" }, { label: "作业许可", path: "/permit" }, { label: "运维承包商", path: "/contractor" }, { label: "培训考核", path: "/training" }, { label: "电量结算", path: "/settlement" }, { label: "车辆调度", path: "/dispatch" }]
</script>
