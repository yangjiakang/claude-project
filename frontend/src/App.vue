<template>
  <div class="app-container">
    <!-- 页头 -->
    <header class="app-header">
      <div class="header-left">
        <span class="logo">🎬</span>
        <h1>视频下载 & 格式转换</h1>
        <span v-if="isRunning" class="badge-running">运行中</span>
      </div>
      <div class="header-right">
        <span class="status-dot" :class="{ online: backendOnline }" />
        <span class="status-text">{{ backendOnline ? '服务就绪' : '服务离线' }}</span>
      </div>
    </header>

    <!-- 主内容 -->
    <main class="app-main">
      <section class="left-panel">
        <VideoForm @start="onScrapeStart" :disabled="isRunning" />
        <DownloadProgress :logs="progressLogs" />
        <FileList :files="downloadedFiles" @convert="onConvertRequest" @refresh="loadFiles" />
      </section>
      <section class="right-panel">
        <HistoryList :history="history" @delete="onDeleteHistory" @refresh="loadHistory" />
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import VideoForm from './components/VideoForm.vue'
import DownloadProgress from './components/DownloadProgress.vue'
import FileList from './components/FileList.vue'
import HistoryList from './components/HistoryList.vue'

const backendOnline = ref(false)
const isRunning = ref(false)
const progressLogs = ref([])
const downloadedFiles = ref([])
const history = ref([])
let eventSource = null

onMounted(() => { checkHealth(); loadFiles(); loadHistory() })
onUnmounted(() => { if (eventSource) eventSource.close() })

const API = (path, opts = {}) => fetch(path, opts).then(r => r.json())

async function checkHealth() {
  try { const r = await API('/api/health'); backendOnline.value = r.status === 'ok' }
  catch { backendOnline.value = false }
}
async function loadFiles() {
  try { downloadedFiles.value = await API('/api/files') }
  catch { downloadedFiles.value = [] }
}
async function loadHistory() {
  try { history.value = await API('/api/history?limit=50') }
  catch { history.value = [] }
}
async function onDeleteHistory(id) {
  try { await fetch(`/api/history/${id}`, { method: 'DELETE' }); history.value = history.value.filter(h => h.id !== id) }
  catch { /* */ }
}

// ===== 爬取控制（自动选择单 URL 或批量模式） =====
async function onScrapeStart(config) {
  if (isRunning.value) return
  isRunning.value = true
  progressLogs.value = []

  // 判断是单 URL 还是批量
  const isBatch = config.urls && config.urls.length > 1
  const endpoint = isBatch ? '/api/scrape-batch' : '/api/scrape'
  const body = isBatch
    ? { urls: config.urls, max_videos_per_url: config.max_videos_per_url, concurrent: config.concurrent,
        skip_head: config.skip_head, timeout: config.timeout }
    : { url: config.urls[0], max_videos: config.max_videos_per_url, concurrent: config.concurrent,
        skip_head: config.skip_head, timeout: config.timeout }

  try {
    await API(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

    eventSource = new EventSource('/api/progress')
    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        progressLogs.value.push({ time: Date.now(), ...data })
        if (data.type === 'complete' || data.type === 'batch_complete') {
          cleanup()
          loadFiles()
          loadHistory()
        } else if (data.type === 'error') {
          // 不立即 cleanup，批量模式下单 URL 失败不影响后续
          if (data.type === 'error' && !isBatch) cleanup()
        }
      } catch { /* */ }
    }
    eventSource.onerror = () => {
      // SSE 断开先不 cleanup，可能是暂时的
    }
  } catch (e) {
    progressLogs.value.push({ time: Date.now(), type: 'error', message: `请求失败: ${e.message}` })
    cleanup()
  }
}

function cleanup() {
  if (eventSource) { eventSource.close(); eventSource = null }
  isRunning.value = false
}

async function onConvertRequest({ filePath, targetFormat, preset, removeOriginal }) {
  progressLogs.value.push({ time: Date.now(), type: 'log', message: `开始转换: → ${targetFormat}` })
  try {
    await API('/api/convert', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath, target_format: targetFormat, preset, remove_original: removeOriginal }),
    })
    eventSource = new EventSource('/api/progress')
    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        progressLogs.value.push({ time: Date.now(), ...data })
        if (data.type === 'convert_complete' || data.type === 'convert_error') {
          if (eventSource) { eventSource.close(); eventSource = null }
          loadFiles(); loadHistory()
        }
      } catch { /* */ }
    }
  } catch (e) {
    progressLogs.value.push({ time: Date.now(), type: 'error', message: `转换失败: ${e.message}` })
  }
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
#app { max-width: 1200px; margin: 0 auto; padding: 20px; }
.app-container { min-height: 100vh; }
.app-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px 0; border-bottom: 1px solid #1e293b; margin-bottom: 24px;
}
.header-left { display: flex; align-items: center; gap: 12px; }
.logo { font-size: 28px; }
.header-left h1 { font-size: 20px; font-weight: 600; }
.badge-running { background: #6366f1; color: #fff; font-size: 11px; padding: 2px 10px; border-radius: 10px; animation: pulse 1.5s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
.header-right { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #94a3b8; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #ef4444; }
.status-dot.online { background: #22c55e; box-shadow: 0 0 8px #22c55e55; }
.app-main { display: grid; grid-template-columns: 1fr 340px; gap: 24px; align-items: start; }
@media (max-width: 900px) { .app-main { grid-template-columns: 1fr; } }
</style>
