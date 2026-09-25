import { createRouter, createWebHistory } from 'vue-router'

import Dashboard from '@/views/Dashboard.vue'
const Station = () => import('@/views/station/index.vue')
const Array = () => import('@/views/array/index.vue')
const Inverter = () => import('@/views/inverter/index.vue')
const Combiner = () => import('@/views/combiner/index.vue')
const Stringmon = () => import('@/views/stringmon/index.vue')
const Irradiance = () => import('@/views/irradiance/index.vue')
const Cleaning = () => import('@/views/cleaning/index.vue')
const Inspection = () => import('@/views/inspection/index.vue')
const Defect = () => import('@/views/defect/index.vue')
const Repair = () => import('@/views/repair/index.vue')
const Sparepart = () => import('@/views/sparepart/index.vue')
const Generation = () => import('@/views/generation/index.vue')
const Curtail = () => import('@/views/curtail/index.vue')
const Alarm = () => import('@/views/alarm/index.vue')
const Permit = () => import('@/views/permit/index.vue')
const Contractor = () => import('@/views/contractor/index.vue')
const Training = () => import('@/views/training/index.vue')
const Settlement = () => import('@/views/settlement/index.vue')
const Dispatch = () => import('@/views/dispatch/index.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/station', name: 'station', component: Station },
    { path: '/array', name: 'array', component: Array },
    { path: '/inverter', name: 'inverter', component: Inverter },
    { path: '/combiner', name: 'combiner', component: Combiner },
    { path: '/stringmon', name: 'stringmon', component: Stringmon },
    { path: '/irradiance', name: 'irradiance', component: Irradiance },
    { path: '/cleaning', name: 'cleaning', component: Cleaning },
    { path: '/inspection', name: 'inspection', component: Inspection },
    { path: '/defect', name: 'defect', component: Defect },
    { path: '/repair', name: 'repair', component: Repair },
    { path: '/sparepart', name: 'sparepart', component: Sparepart },
    { path: '/generation', name: 'generation', component: Generation },
    { path: '/curtail', name: 'curtail', component: Curtail },
    { path: '/alarm', name: 'alarm', component: Alarm },
    { path: '/permit', name: 'permit', component: Permit },
    { path: '/contractor', name: 'contractor', component: Contractor },
    { path: '/training', name: 'training', component: Training },
    { path: '/settlement', name: 'settlement', component: Settlement },
    { path: '/dispatch', name: 'dispatch', component: Dispatch },
  ],
})

export default router
