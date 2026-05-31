<template>
  <!-- 批量下载进度 —— 每个 URL 独立进度卡片 -->
  <div class="card" v-if="urlProgressList.length > 0 || logs.length > 0">
    <h2 class="card-title">📊 下载进度</h2>

    <!-- 总进度条 -->
    <div class="progress-section">
      <div class="progress-bar-bg">
        <div class="progress-bar-fill" :style="{ width: overallPercent + '%' }" />
      </div>
      <span class="progress-text">{{ overallPercent }}%</span>
    </div>
    <div class="overall-label">{{ completedUrls }} / {{ totalUrls }} 个 URL 完成</div>

    <!-- 每个 URL 的独立进度卡片 -->
    <div class="url-progress-list">
      <div
        v-for="up in urlProgressList"
        :key="up.urlIndex"
        class="url-card"
        :class="{ 'url-done': up.status === 'done', 'url-active': up.status === 'active', 'url-error': up.status === 'error' }"
      >
        <div class="url-card-header">
          <span class="url-status-icon">
            {{ up.status === 'done' ? '✅' : up.status === 'error' ? '❌' : '⏳' }}
          </span>
          <span class="url-label">#{{ up.urlIndex + 1 }}</span>
          <span class="url-addr" :title="up.url">{{ truncate(up.url, 45) }}</span>
        </div>
        <!-- 单个 URL 的进度条 -->
        <div class="url-bar-bg">
          <div class="url-bar-fill" :class="up.status" :style="{ width: up.percent + '%' }" />
        </div>
        <div class="url-meta">{{ up.message }}</div>
      </div>
    </div>

    <!-- 日志区 -->
    <div class="log-area" ref="logRef">
      <div v-for="(log, i) in logs" :key="i" class="log-line"
        :class="{ 'log-error': log.type === 'error', 'log-highlight': log.type === 'ffmpeg_progress' }">
        <span class="log-time">{{ formatTime(log.time) }}</span>
        <span>{{ log.message }}</span>
      </div>
      <div v-if="logs.length === 0" class="log-empty">等待开始...</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, reactive } from 'vue'

const props = defineProps({ logs: Array })

const logRef = ref(null)
const totalUrls = ref(0)       // batch_start 中的总数
const completedUrls = ref(0)    // url_complete 的计数

// 每个 URL 的进度状态: { urlIndex, url, percent, status, message }
const urlProgressMap = reactive({})

const urlProgressList = computed(() =>
  Object.values(urlProgressMap).sort((a, b) => a.urlIndex - b.urlIndex)
)

const overallPercent = computed(() => {
  if (totalUrls.value === 0) return 0
  const sum = urlProgressList.value.reduce((s, u) => s + (u.percent || 0), 0)
  return Math.round(sum / totalUrls.value)
})

watch(() => props.logs.length, () => {
  nextTick(() => { if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight })
  // 解析最新日志更新各 URL 进度
  const latest = props.logs[props.logs.length - 1]
  if (!latest) return
  if (latest.type === 'batch_start') totalUrls.value = latest.total || 0
  if (latest.type === 'url_start' && latest.url_index != null) {
    urlProgressMap[latest.url_index] = {
      urlIndex: latest.url_index, url: latest.url || '', percent: 0, status: 'active', message: latest.message
    }
  }
  if (latest.type === 'url_complete' && latest.url_index != null) {
    const u = urlProgressMap[latest.url_index]
    if (u) { u.status = 'done'; u.percent = 100; u.message = latest.message }
    completedUrls.value = Math.max(completedUrls.value, (latest.url_index || 0) + 1)
  }
  if (latest.type === 'url_error' && latest.url_index != null) {
    const u = urlProgressMap[latest.url_index]
    if (u) { u.status = 'error'; u.message = latest.message }
  }
  if (latest.type === 'ffmpeg_progress' && latest.url_index != null && latest.percent != null) {
    const u = urlProgressMap[latest.url_index]
    if (u) { u.percent = latest.percent; u.message = latest.message }
  }
  if (latest.type === 'batch_complete') {
    completedUrls.value = latest.total || totalUrls.value
    // 所有剩余 URL 标记完成
    for (const u of urlProgressList.value) {
      if (u.status === 'active') { u.status = 'done'; u.percent = 100 }
    }
  }
})

const truncate = (s, n) => s && s.length > n ? s.slice(0, n) + '...' : (s || '')
const formatTime = (ts) => {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`
}
</script>

<style scoped>
.card { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
.card-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; }

/* 总进度条 */
.progress-section { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
.progress-bar-bg { flex: 1; height: 8px; background: #0f172a; border-radius: 4px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #22c55e); border-radius: 4px; transition: width 0.5s ease; }
.progress-text { font-size: 13px; font-weight: 600; color: #e2e8f0; min-width: 36px; text-align: right; }
.overall-label { font-size: 11px; color: #64748b; margin-bottom: 14px; }

/* 每个 URL 的进度卡片 */
.url-progress-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.url-card { background: #0f172a; border-radius: 8px; padding: 10px 12px; border-left: 3px solid #334155; transition: border-color 0.3s; }
.url-card.url-active { border-left-color: #6366f1; }
.url-card.url-done { border-left-color: #22c55e; }
.url-card.url-error { border-left-color: #ef4444; }
.url-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.url-status-icon { font-size: 14px; }
.url-label { font-size: 11px; color: #64748b; font-weight: 500; }
.url-addr { font-size: 12px; color: #94a3b8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.url-bar-bg { height: 4px; background: #1e293b; border-radius: 2px; overflow: hidden; margin-bottom: 4px; }
.url-bar-fill { height: 100%; background: #6366f1; border-radius: 2px; transition: width 0.5s ease; }
.url-bar-fill.done { background: #22c55e; }
.url-bar-fill.error { background: #ef4444; }
.url-meta { font-size: 11px; color: #64748b; }

/* 日志 */
.log-area { background: #0f172a; border-radius: 8px; padding: 10px; max-height: 150px; overflow-y: auto; font-family: 'Menlo', monospace; font-size: 11px; line-height: 1.6; }
.log-line { color: #94a3b8; }
.log-error { color: #ef4444; }
.log-highlight { color: #a5b4fc; }
.log-time { color: #64748b; margin-right: 6px; }
.log-empty { color: #475569; text-align: center; padding: 12px; }
</style>
