<template>
  <div v-if="open" class="modal-mask" @click.self="$emit('close')">
    <div class="modal wide">
      <header class="modal-head">
        <h3>批量派车（{{ tasks.length }} 条待出车任务）</h3>
        <button class="link" type="button" @click="$emit('close')">关闭</button>
      </header>

      <!-- 第一步：逐条填写用车时间与首选司机/车辆 -->
      <div v-if="stage === 'edit'" class="modal-body">
        <p class="page-desc">逐台选择用车时段与首选司机、车辆；首选被占用时系统按优先级自动顺延，逐台返回结果。</p>
        <table class="data-table dispatch-edit-table">
          <thead>
            <tr>
              <th style="width: 40px">#</th>
              <th>作业任务</th>
              <th>目的地</th>
              <th>用车开始</th>
              <th>用车结束</th>
              <th>首选车辆（优先级）</th>
              <th>首选司机（优先级）</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(task, index) in tasks" :key="task.task_ref">
              <td>{{ index + 1 }}</td>
              <td>
                <span class="tag" :class="task.任务类型 === '巡检' ? 'tag-blue' : 'tag-orange'">{{ task.任务类型 }}</span>
                {{ task.任务单号 }}
              </td>
              <td>{{ task.目的地 || '—' }}</td>
              <td>
                <input
                  v-model="forms[index].start_time"
                  type="datetime-local"
                  :class="{ invalid: !forms[index].start_time }"
                />
              </td>
              <td>
                <input
                  v-model="forms[index].end_time"
                  type="datetime-local"
                  :class="{ invalid: !forms[index].end_time }"
                />
              </td>
              <td>
                <select v-model="forms[index].vehicle_id">
                  <option :value="null">按优先级自动安排</option>
                  <option v-for="v in vehicles" :key="v.id" :value="v.id">
                    P{{ v.优先级 }} {{ v.车牌 }}（{{ v.车辆状态 }}）
                  </option>
                </select>
              </td>
              <td>
                <select v-model="forms[index].driver_id">
                  <option :value="null">按优先级自动安排</option>
                  <option v-for="d in drivers" :key="d.id" :value="d.id">
                    P{{ d.优先级 }} {{ d.司机姓名 }}（{{ d.司机状态 }}）
                  </option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 第二步：逐台派车结果，失败单独标红，绝不能显示成全部成功 -->
      <div v-else class="modal-body">
        <div class="result-banner" :class="result && result.全部成功 ? 'banner-ok' : 'banner-warn'">
          <strong>
            {{ result && result.全部成功 ? '全部派车成功' : '部分派车失败' }}
          </strong>
          <span v-if="result">
            批次 {{ result.批次号 }} · 成功 {{ result.成功数 }} 台 · 失败 {{ result.失败数 }} 台
            <em v-if="result.replayed">（本次为重复提交，已回放首次结果，未重复派车）</em>
          </span>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 40px">#</th>
              <th style="width: 64px">结果</th>
              <th>作业任务</th>
              <th>用车时段</th>
              <th>派车结果（车牌 / 司机）</th>
              <th>顺延说明 / 失败原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in resultItems" :key="String(item.序号)" :class="{ 'row-fail': !item.ok }">
              <td>{{ item.序号 }}</td>
              <td>
                <span class="tag" :class="item.ok ? 'tag-green' : 'tag-red'">{{ item.ok ? '成功' : '失败' }}</span>
              </td>
              <td>
                <span class="tag" :class="item.任务类型 === '巡检' ? 'tag-blue' : 'tag-orange'">{{ item.任务类型 }}</span>
                {{ item.任务单号 }}
              </td>
              <td>{{ item.开始时间 }} ~ {{ item.结束时间 }}</td>
              <td v-if="item.ok">
                <strong>{{ item.车牌 }}</strong> / {{ item.司机 }}
                <span v-if="item.顺延车辆 || item.顺延司机" class="tag tag-amber">含优先级顺延</span>
              </td>
              <td v-else class="error-text">未派出</td>
              <td>
                <p v-if="item.ok" class="cell-note">
                  {{ item.说明 || '首选司机、车辆均按原选择派出，无冲突' }}
                </p>
                <p v-else class="error-text cell-note">{{ item.失败原因 }}</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer class="modal-foot">
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
        <template v-if="stage === 'edit'">
          <button class="btn ghost" type="button" @click="$emit('close')">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submit">
            {{ submitting ? '派车中…' : `一次提交派车（${tasks.length} 台）` }}
          </button>
        </template>
        <template v-else>
          <button class="btn" type="button" @click="$emit('close')">关闭</button>
          <button class="btn primary" type="button" @click="$emit('done')">查看派车结果</button>
        </template>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import { request } from '@/api/client'

interface Candidate {
  task_ref: string
  任务类型: string
  任务单号: string
  任务名称: string
  目的地: string
  可派车: boolean
  [key: string]: unknown
}
interface Resource {
  id: number
  优先级?: number
  [key: string]: unknown
}
interface DispatchResultItem {
  序号: number
  ok: boolean
  任务类型: string
  任务单号: string
  开始时间: string
  结束时间: string
  车牌: string | null
  司机: string | null
  顺延车辆: boolean
  顺延司机: boolean
  说明: string
  失败原因: string | null
  [key: string]: unknown
}
interface BatchResult {
  批次号: string
  全部成功: boolean
  成功数: number
  失败数: number
  replayed: boolean
  items: DispatchResultItem[]
}

const props = defineProps<{
  open: boolean
  tasks: Candidate[]
  vehicles: Resource[]
  drivers: Resource[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'done'): void
}>()

const stage = ref<'edit' | 'result'>('edit')
const submitting = ref(false)
const errorMessage = ref('')
const result = ref<BatchResult | null>(null)
const forms = reactive<Record<number, { start_time: string; end_time: string; vehicle_id: number | null; driver_id: number | null }>>({})

function defaultTime(base: Date, hour: number): string {
  const d = new Date(base)
  d.setHours(hour, 0, 0, 0)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    stage.value = 'edit'
    result.value = null
    errorMessage.value = ''
    const morning = new Date()
    const evening = new Date()
    props.tasks.forEach((_, index) => {
      forms[index] = {
        start_time: defaultTime(morning, 8),
        end_time: defaultTime(evening, 12),
        vehicle_id: null,
        driver_id: null,
      }
    })
  },
)

const resultItems = computed<DispatchResultItem[]>(() => result.value?.items ?? [])

async function submit() {
  errorMessage.value = ''
  const missing = props.tasks.filter((_, index) => !forms[index]?.start_time || !forms[index]?.end_time)
  if (missing.length) {
    errorMessage.value = `还有 ${missing.length} 条任务没填完整用车时间`
    return
  }
  const badRange = props.tasks.filter((_, index) => forms[index].end_time <= forms[index].start_time)
  if (badRange.length) {
    errorMessage.value = `有 ${badRange.length} 条任务的结束时间早于开始时间，请修正`
    return
  }

  // idem_key 只在“新的一次提交动作”时生成；超时重试沿用同一个 key，后端据此防重。
  const idemKey = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const items = props.tasks.map((task, index) => ({
    task_ref: task.task_ref,
    start_time: forms[index].start_time.replace('T', ' '),
    end_time: forms[index].end_time.replace('T', ' '),
    vehicle_id: forms[index].vehicle_id,
    driver_id: forms[index].driver_id,
  }))

  submitting.value = true
  try {
    const response = await request('/api/dispatch/batches', {
      method: 'POST',
      body: JSON.stringify({ idem_key: idemKey, items }),
    })
    if (!response.ok) {
      const detail = await response.json().catch(() => null)
      throw new Error(detail?.detail ?? '派车提交失败')
    }
    result.value = (await response.json()) as BatchResult
    stage.value = 'result'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '派车提交失败'
  } finally {
    submitting.value = false
  }
}
</script>
