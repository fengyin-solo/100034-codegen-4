<template>
  <section class="page" data-module="dispatch">
    <header class="page-head">
      <div>
        <h2>车辆调度</h2>
        <p class="page-desc">
          勾选多条巡检/消缺待出车任务一次提交，逐台派车；司机或车辆时间冲突时按优先级顺延并逐台标注原因，
          司机确认出车后可在行车记录中查看。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="!selected.length" @click="openDispatch">
          派车（已选 {{ selected.length }} 条）
        </button>
        <button class="btn" type="button" @click="reload">刷新</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="tab"
        :class="{ active: activeTab === tab.key }"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <footer v-if="errorMessage" class="page-foot">
      <span class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 待出车任务 -->
    <template v-if="activeTab === 'candidate'">
      <table class="data-table">
        <thead>
          <tr>
            <th style="width: 40px">选择</th>
            <th>任务类型</th>
            <th>任务单号</th>
            <th>任务名称</th>
            <th>目的地</th>
            <th>原列表状态</th>
            <th>可派车</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in candidates" :key="row.task_ref" :class="{ 'row-disabled': !row.可派车 }">
            <td>
              <input
                type="checkbox"
                :value="row.task_ref"
                :disabled="!row.可派车"
                v-model="checkedRefs"
              />
            </td>
            <td><span class="tag" :class="row.任务类型 === '巡检' ? 'tag-blue' : 'tag-orange'">{{ row.任务类型 }}</span></td>
            <td>{{ row.任务单号 }}</td>
            <td>{{ row.任务名称 }}</td>
            <td>{{ row.目的地 }}</td>
            <td>{{ row.原始状态 }}</td>
            <td>
              <span v-if="row.可派车" class="tag tag-green">待出车</span>
              <span v-else class="error-text">{{ row.占用说明 }}</span>
            </td>
          </tr>
          <tr v-if="!candidates.length">
            <td colspan="7" class="empty-state">暂无待出车任务（巡检「待派发」、消缺「待受理」才会出现在这里）</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ candidates.length }} 条待出车任务，候选数据只读来自巡检/消缺列表，不改变原任务</span>
      </footer>
    </template>

    <!-- 派车结果 -->
    <template v-else-if="activeTab === 'orders'">
      <form class="filter-bar" @submit.prevent="reloadOrders">
        <label class="filter-item">
          <span>批次号</span>
          <input v-model="orderFilter.batch_id" placeholder="如 DISP-20260925-01" />
        </label>
        <label class="filter-item">
          <span>派车单状态</span>
          <select v-model="orderFilter.status">
            <option value="">全部</option>
            <option v-for="s in orderStatuses" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>关键字</span>
          <input v-model="orderFilter.keyword" placeholder="任务单号/车牌/司机/目的地" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetOrderFilter">重置</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>派车单</th>
            <th>批次号</th>
            <th>作业任务</th>
            <th>用车时段</th>
            <th>车辆/司机</th>
            <th>顺延</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in orders" :key="String(row.id)">
            <td>#{{ row.id }}</td>
            <td>{{ row.批次号 }}</td>
            <td>
              <span class="tag" :class="row.任务类型 === '巡检' ? 'tag-blue' : 'tag-orange'">{{ row.任务类型 }}</span>
              {{ row.任务单号 }} · {{ row.目的地 }}
            </td>
            <td>{{ row.开始时间 }} ~ {{ row.结束时间 }}</td>
            <td>{{ row.车牌 }} / {{ row.司机 }}（{{ row.联系电话 }}）</td>
            <td>
              <span v-if="row.顺延车辆 || row.顺延司机" class="tag tag-amber">
                {{ [row.顺延车辆 ? '车' : '', row.顺延司机 ? '司机' : ''].filter(Boolean).join('、') }}顺延
              </span>
              <span v-else class="muted-text">原选择</span>
            </td>
            <td>
              <span class="tag" :class="statusTagClass(row.status)">{{ row.status }}</span>
            </td>
            <td class="row-actions">
              <button v-if="row.status === '待确认出车'" class="link" type="button" @click="confirmOrder(row)">
                确认出车
              </button>
              <button
                v-if="row.status === '待确认出车'"
                class="link danger"
                type="button"
                @click="withdrawOne(row)"
              >
                撤回
              </button>
              <span v-else-if="row.status === '已出车'" class="muted-text">行车记录已生成</span>
              <span v-else-if="row.status === '已撤回'" class="muted-text">已释放车辆/司机</span>
            </td>
          </tr>
          <tr v-if="!orders.length">
            <td colspan="8" class="empty-state">暂无派车单</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ orderTotal }} 张派车单；撤回只改状态不删行，已出车的单不会被清掉</span>
      </footer>
    </template>

    <!-- 行车记录（司机视角） -->
    <template v-else>
      <form class="filter-bar" @submit.prevent="reloadTrips">
        <label class="filter-item">
          <span>司机姓名</span>
          <input v-model="tripDriver" list="driver-options" placeholder="留空查看全部司机" />
          <datalist id="driver-options">
            <option v-for="d in drivers" :key="d.id" :value="String(d.司机姓名)"></option>
          </datalist>
        </label>
        <button class="btn" type="submit">查询我的行车记录</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>记录单号</th>
            <th>作业任务</th>
            <th>用车时段</th>
            <th>车辆</th>
            <th>司机</th>
            <th>确认出车时间</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in trips" :key="String(row.id)">
            <td>#{{ row.id }}（批次 {{ row.批次号 }}）</td>
            <td>
              <span class="tag" :class="row.任务类型 === '巡检' ? 'tag-blue' : 'tag-orange'">{{ row.任务类型 }}</span>
              {{ row.任务单号 }} · {{ row.目的地 }}
            </td>
            <td>{{ row.开始时间 }} ~ {{ row.结束时间 }}</td>
            <td>{{ row.车牌 }}</td>
            <td>{{ row.司机 }}（{{ row.联系电话 }}）</td>
            <td>{{ row.confirmed_at || '—' }}</td>
            <td><span class="tag tag-green">{{ row.status }}</span></td>
          </tr>
          <tr v-if="!trips.length">
            <td colspan="7" class="empty-state">暂无行车记录：派车单经司机确认出车后才会出现在这里</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ tripTotal }} 条行车记录，与派车结果同源，撤回派车不会删掉已出车的记录</span>
      </footer>
    </template>

    <DispatchModal
      :open="modalOpen"
      :tasks="selectedTasks"
      :vehicles="vehicles"
      :drivers="drivers"
      @close="modalOpen = false"
      @done="afterDispatched"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

import DispatchModal from './DispatchModal.vue'

interface Candidate {
  task_ref: string
  任务类型: string
  任务单号: string
  任务名称: string
  目的地: string
  原始状态: string
  可派车: boolean
  占用说明: string
}
interface Resource {
  id: number
  优先级?: number
  [key: string]: unknown
}
type OrderRow = Record<string, string | number | boolean | null>

const tabs = [
  { key: 'candidate', label: '待出车任务' },
  { key: 'orders', label: '派车结果' },
  { key: 'trips', label: '行车记录' },
] as const

const activeTab = ref<(typeof tabs)[number]['key']>('candidate')
const candidates = ref<Candidate[]>([])
const vehicles = ref<Resource[]>([])
const drivers = ref<Resource[]>([])
const checkedRefs = ref<string[]>([])
const modalOpen = ref(false)
const errorMessage = ref('')

const orders = ref<OrderRow[]>([])
const orderTotal = ref(0)
const orderFilter = ref<Record<string, string>>({ batch_id: '', status: '', keyword: '' })
const orderStatuses = ['待确认出车', '已出车', '已完成', '已撤回']

const trips = ref<OrderRow[]>([])
const tripTotal = ref(0)
const tripDriver = ref('')

const selectedTasks = computed(() =>
  candidates.value.filter((row) => checkedRefs.value.includes(row.task_ref)),
)
const selected = computed(() => checkedRefs.value)

const stats = computed(() => [
  { label: '待出车任务', value: candidates.value.length },
  { label: '可用车辆', value: vehicles.value.filter((v) => v.车辆状态 === '可用').length },
  { label: '可派司机', value: drivers.value.filter((d) => d.司机状态 === '可派').length },
  {
    label: '待确认出车单',
    value: orders.value.filter((row) => row.status === '待确认出车').length,
  },
])

async function loadResources() {
  try {
    const response = await request('/api/dispatch/resources')
    if (!response.ok) throw new Error('调度资源读取失败')
    const data = await response.json()
    vehicles.value = data.vehicles ?? []
    drivers.value = data.drivers ?? []
    candidates.value = data.candidates ?? []
    // 只保留仍可选的勾选项，避免资源刷新后把不可派的任务带进弹窗。
    checkedRefs.value = checkedRefs.value.filter((ref) =>
      candidates.value.some((row) => row.task_ref === ref && row.可派车),
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '调度资源读取失败'
  }
}

async function reloadOrders() {
  const params = new URLSearchParams()
  Object.entries(orderFilter.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  params.set('size', '200')
  try {
    const response = await request(`/api/dispatch/orders?${params.toString()}`)
    if (!response.ok) throw new Error('派车结果读取失败')
    const data = await response.json()
    orders.value = data.items ?? []
    orderTotal.value = data.total ?? orders.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '派车结果读取失败'
  }
}

function resetOrderFilter() {
  orderFilter.value = { batch_id: '', status: '', keyword: '' }
  void reloadOrders()
}

async function reloadTrips() {
  const params = new URLSearchParams({ size: '200' })
  if (tripDriver.value.trim()) params.set('driver', tripDriver.value.trim())
  try {
    const response = await request(`/api/dispatch/trips?${params.toString()}`)
    if (!response.ok) throw new Error('行车记录读取失败')
    const data = await response.json()
    trips.value = data.items ?? []
    tripTotal.value = data.total ?? trips.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '行车记录读取失败'
  }
}

async function reload() {
  await loadResources()
  await reloadOrders()
  await reloadTrips()
}

function switchTab(key: (typeof tabs)[number]['key']) {
  activeTab.value = key
  errorMessage.value = ''
}

function openDispatch() {
  if (!selectedTasks.value.length) return
  errorMessage.value = ''
  modalOpen.value = true
}

async function afterDispatched() {
  modalOpen.value = false
  checkedRefs.value = []
  activeTab.value = 'orders'
  await reload()
}

async function confirmOrder(row: OrderRow) {
  errorMessage.value = ''
  try {
    const response = await request(`/api/dispatch/orders/${row.id}/confirm`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) throw new Error(data?.detail ?? '确认出车失败')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '确认出车失败'
  }
}

async function withdrawOne(row: OrderRow) {
  errorMessage.value = ''
  if (!window.confirm(`确定撤回派车单 #${row.id}（${row.任务单号}）吗？撤回后车辆/司机时段释放。`)) return
  try {
    const response = await request('/api/dispatch/withdraw', {
      method: 'POST',
      body: JSON.stringify({ ids: [Number(row.id)] }),
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) throw new Error(data?.detail ?? '撤回失败')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '撤回失败'
  }
}

function statusTagClass(status: unknown) {
  if (status === '已出车' || status === '已完成') return 'tag-green'
  if (status === '已撤回') return 'tag-gray'
  return 'tag-amber'
}

onMounted(reload)
</script>
