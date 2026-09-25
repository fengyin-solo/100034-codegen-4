<template>
  <section class="page" data-module="dispatch">
    <header class="page-head">
      <div>
        <h2>车辆调度</h2>
        <p class="page-desc">从巡检、消缺任务里勾选待出车作业一次提交派车；时间冲突按优先级顺延，被占用的司机或车辆逐台标出原因，整批不退回。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="!selectedKeys.length" @click="openDialog">
          批量派车（已选 {{ selectedKeys.length }} 条）
        </button>
        <button class="btn" type="button" @click="reloadAll">刷新</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <h3 class="section-title">待出车作业任务</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>选择</th>
          <th v-for="column in taskColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="task in tasks" :key="task.task_key">
          <td><input v-model="selectedKeys" type="checkbox" :value="task.task_key" /></td>
          <td v-for="column in taskColumns" :key="column">{{ task[column] ?? '—' }}</td>
        </tr>
        <tr v-if="!tasks.length">
          <td :colspan="taskColumns.length + 1" class="empty-state">暂无待出车的作业任务，巡检或消缺在办单据会自动进入这里</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">派车单</h3>
    <form class="filter-bar" @submit.prevent>
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="dispatchKeyword" placeholder="按派车单号、司机、车牌检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="dispatchStatus">
          <option value="">全部</option>
          <option v-for="item in dispatchStatuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
    </form>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in dispatchColumns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in filteredDispatches" :key="String(row.id)">
          <td v-for="column in dispatchColumns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in rowActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!filteredDispatches.length">
          <td :colspan="dispatchColumns.length + 1" class="empty-state">暂无派车单，可先在上方勾选任务批量派车</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">行车记录</h3>
    <form class="filter-bar" @submit.prevent>
      <label class="filter-item">
        <span>司机姓名</span>
        <input v-model="tripDriver" placeholder="司机确认出车后可在这里查自己的行程" />
      </label>
    </form>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in tripColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in filteredTrips" :key="String(row.id)">
          <td v-for="column in tripColumns" :key="column">{{ row[column] || '—' }}</td>
        </tr>
        <tr v-if="!filteredTrips.length">
          <td :colspan="tripColumns.length" class="empty-state">暂无行车记录，司机确认出车后自动生成</td>
        </tr>
      </tbody>
    </table>

    <div v-if="dialogOpen" class="modal-mask">
      <div class="modal-panel">
        <header class="modal-head">
          <h3>批量派车（{{ dialogRows.length }} 台）</h3>
          <button class="link" type="button" @click="closeDialog">关闭</button>
        </header>
        <p v-if="batchMessage" class="batch-summary" :class="{ warn: summaryHasIssue }">{{ batchMessage }}</p>
        <table class="data-table">
          <thead>
            <tr>
              <th>任务单号</th>
              <th>目的地</th>
              <th>车辆</th>
              <th>司机</th>
              <th>计划出车</th>
              <th>计划返回</th>
              <th>优先级</th>
              <th>排车结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in dialogRows" :key="row.task_key">
              <td>{{ row.任务单号 }}</td>
              <td>{{ row.目的地 }}</td>
              <td>
                <select v-model.number="row.vehicle_id" :disabled="row.done" @change="markEdited">
                  <option v-for="vehicle in vehicles" :key="vehicle.id" :value="vehicle.id" :disabled="vehicle.status !== '可用'">
                    {{ vehicle.车牌号 }}（{{ vehicle.status }}）
                  </option>
                </select>
              </td>
              <td>
                <select v-model.number="row.driver_id" :disabled="row.done" @change="markEdited">
                  <option v-for="driver in drivers" :key="driver.id" :value="driver.id" :disabled="driver.status !== '在岗'">
                    {{ driver.司机姓名 }}（{{ driver.status }}）
                  </option>
                </select>
              </td>
              <td><input v-model="row.start" type="datetime-local" :disabled="row.done" @change="markEdited" /></td>
              <td><input v-model="row.end" type="datetime-local" :disabled="row.done" @change="markEdited" /></td>
              <td>
                <select v-model="row.priority" :disabled="row.done" @change="markEdited">
                  <option>高</option>
                  <option>中</option>
                  <option>低</option>
                </select>
              </td>
              <td class="result-cell">
                <span v-if="row.result" class="tag" :class="resultClass(row.result)">{{ row.result }}</span>
                <span v-if="row.reason" class="reason-text">{{ row.reason }}</span>
                <span v-if="row.result === '已顺延'" class="reason-text">新时间 {{ row.计划出车时间 }}~{{ row.计划返回时间 }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <footer class="modal-foot">
          <span v-if="dialogError" class="error-text">{{ dialogError }}</span>
          <button class="btn primary" type="button" :disabled="submitting || !pendingRows.length" @click="submitBatch">
            {{ submitting ? '提交中…' : `提交派车（${pendingRows.length} 台）` }}
          </button>
        </footer>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ dispatches.length }} 条派车单 · {{ trips.length }} 条行车记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

type DialogRow = {
  task_key: string
  任务单号: string
  目的地: string
  vehicle_id: number
  driver_id: number
  start: string
  end: string
  priority: string
  result: string
  reason: string
  计划出车时间: string
  计划返回时间: string
  done: boolean
}

const ENDPOINT = '/api/dispatch'
const taskColumns = ['任务来源', '任务单号', '目的地', '建议出车时间', '任务状态']
const dispatchColumns = ['派车单号', '任务单号', '司机', '车牌号', '计划出车时间', '计划返回时间', '优先级', '顺延次数', 'status']
const tripColumns = ['记录编号', '派车单号', '任务单号', '司机', '车牌号', '出车时间', '返回时间', 'status']
const dispatchStatuses = ['待出车', '已出车', '已完成', '已撤回']

const tasks = ref<Row[]>([])
const selectedKeys = ref<string[]>([])
const dispatches = ref<Row[]>([])
const trips = ref<Row[]>([])
const vehicles = ref<Row[]>([])
const drivers = ref<Row[]>([])
const dispatchKeyword = ref('')
const dispatchStatus = ref('')
const tripDriver = ref('')
const errorMessage = ref('')

const dialogOpen = ref(false)
const dialogRows = ref<DialogRow[]>([])
const batchId = ref('')
const batchMessage = ref('')
const summaryHasIssue = ref(false)
const submitting = ref(false)
const dialogError = ref('')

const stats = computed(() => [
  { label: '待出车任务', value: tasks.value.length },
  { label: '待出车派车单', value: dispatches.value.filter((row) => row.status === '待出车').length },
  { label: '行程中', value: dispatches.value.filter((row) => row.status === '已出车').length },
  { label: '行车记录', value: trips.value.length },
])

const filteredDispatches = computed(() => {
  const keyword = dispatchKeyword.value.trim()
  return dispatches.value.filter((row) => {
    if (dispatchStatus.value && row.status !== dispatchStatus.value) return false
    if (!keyword) return true
    return [row.派车单号, row.任务单号, row.司机, row.车牌号].some((field) => String(field ?? '').includes(keyword))
  })
})

const filteredTrips = computed(() => {
  const keyword = tripDriver.value.trim()
  if (!keyword) return trips.value
  return trips.value.filter((row) => String(row.司机 ?? '').includes(keyword))
})

const pendingRows = computed(() => dialogRows.value.filter((row) => !row.done))

function rowActions(row: Row): string[] {
  if (row.status === '待出车') return ['确认出车', '撤回派车']
  if (row.status === '已出车') return ['确认归队', '撤回派车']
  return []
}

function resultClass(result: string): string {
  if (result === '成功') return 'ok'
  if (result === '已顺延') return 'warn'
  return 'fail'
}

function toLocalInput(moment: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}T${pad(moment.getHours())}:${pad(moment.getMinutes())}`
}

function newBatchId(): string {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `B${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function openDialog() {
  const start = new Date()
  start.setMinutes(0, 0, 0)
  start.setHours(start.getHours() + 1)
  const end = new Date(start)
  end.setHours(end.getHours() + 2)
  const firstVehicle = vehicles.value.find((row) => row.status === '可用')
  const firstDriver = drivers.value.find((row) => row.status === '在岗')
  dialogRows.value = tasks.value
    .filter((task) => selectedKeys.value.includes(task.task_key))
    .map((task) => ({
      task_key: task.task_key,
      任务单号: task.任务单号,
      目的地: task.目的地,
      vehicle_id: firstVehicle?.id ?? 0,
      driver_id: firstDriver?.id ?? 0,
      start: toLocalInput(start),
      end: toLocalInput(end),
      priority: '中',
      result: '',
      reason: '',
      计划出车时间: '',
      计划返回时间: '',
      done: false,
    }))
  batchId.value = newBatchId()
  batchMessage.value = ''
  summaryHasIssue.value = false
  dialogError.value = ''
  dialogOpen.value = true
}

function closeDialog() {
  dialogOpen.value = false
}

// 弹窗里改过任何一项就换新的批次号：没改过的重复点击仍走原批次，服务端按幂等键去重
function markEdited() {
  batchId.value = newBatchId()
}

async function submitBatch() {
  const targets = pendingRows.value
  if (!targets.length || submitting.value) return
  submitting.value = true
  dialogError.value = ''
  try {
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({
        batch_id: batchId.value,
        items: targets.map((row) => ({
          task_key: row.task_key,
          vehicle_id: row.vehicle_id,
          driver_id: row.driver_id,
          start: row.start,
          end: row.end,
          priority: row.priority,
        })),
      }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail || '批量派车提交失败')
    }
    for (const item of payload.results ?? []) {
      const row = dialogRows.value.find((entry) => entry.task_key === item.task_key)
      if (!row) continue
      row.result = item.result
      row.reason = item.reason
      row.计划出车时间 = item.计划出车时间 ?? ''
      row.计划返回时间 = item.计划返回时间 ?? ''
      row.done = item.result !== '失败'
    }
    batchMessage.value = payload.message ?? ''
    const summary = payload.summary ?? {}
    summaryHasIssue.value = Number(summary.deferred ?? 0) + Number(summary.failed ?? 0) > 0
    await reloadAll()
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '批量派车提交失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || payload.detail || '派车单动作未生效，请稍后重试')
    }
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '派车单操作失败'
  }
}

async function reloadAll() {
  errorMessage.value = ''
  try {
    const [taskRes, dispatchRes, tripRes, resourceRes] = await Promise.all([
      request(`${ENDPOINT}/tasks`),
      request(`${ENDPOINT}?size=200`),
      request(`${ENDPOINT}/trips?size=200`),
      request(`${ENDPOINT}/resources`),
    ])
    if (!taskRes.ok || !dispatchRes.ok || !tripRes.ok || !resourceRes.ok) {
      throw new Error('车辆调度数据读取失败')
    }
    tasks.value = (await taskRes.json()).items ?? []
    dispatches.value = (await dispatchRes.json()).items ?? []
    trips.value = (await tripRes.json()).items ?? []
    const resources = await resourceRes.json()
    vehicles.value = resources.vehicles ?? []
    drivers.value = resources.drivers ?? []
    selectedKeys.value = selectedKeys.value.filter((key) => tasks.value.some((task) => task.task_key === key))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '车辆调度数据读取失败'
  }
}

onMounted(reloadAll)
</script>
