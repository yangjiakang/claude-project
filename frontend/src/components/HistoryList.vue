<template>
  <!-- 侧边栏：下载/转换历史记录 -->
  <div class="card">
    <div class="card-header">
      <h2 class="card-title">📜 历史记录</h2>
      <button class="btn-refresh" @click="$emit('refresh')">🔄</button>
    </div>

    <div v-if="history.length === 0" class="empty">暂无历史记录</div>

    <div class="history-list">
      <div v-for="item in history" :key="item.id" class="history-item">
        <!-- 状态图标 -->
        <span class="status-icon">{{ statusIcon(item.status) }}</span>
        <div class="item-content">
          <!-- 文件名 + 格式标签 -->
          <div class="item-top">
            <span class="item-filename">{{ item.filename }}</span>
            <span class="badge" :class="item.status">{{ item.format.toUpperCase() }}</span>
          </div>
          <!-- 来源 URL -->
          <div class="item-url" :title="item.url">
            {{ item.url.startsWith('convert://') ? '格式转换任务' : truncate(item.url, 50) }}
          </div>
          <!-- 元信息：大小、时长、时间 -->
          <div class="item-meta">
            <span>{{ item.file_size_mb }} MB</span>
            <span>·</span>
            <span>{{ formatDuration(item.duration_sec) }}</span>
            <span>·</span>
            <span>{{ formatDate(item.created_at) }}</span>
          </div>
        </div>
        <!-- 删除按钮 -->
        <button class="btn-delete" @click="$emit('delete', item.id)" title="删除记录">×</button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ history: Array })
defineEmits(['delete', 'refresh'])

const statusIcon = (s) => ({ completed: '✅', converted: '🔄', failed: '❌' }[s] || '📄')
const truncate = (s, n) => s.length > n ? s.slice(0, n) + '...' : s
const formatDuration = (s) => {
  if (!s || s <= 0) return '--'
  const m = Math.floor(s / 60), sec = Math.floor(s % 60)
  return m >= 60 ? `${Math.floor(m/60)}h${m%60}m` : `${m}m${sec}s`
}
const formatDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
}
</script>

<style scoped>
.card { background: #1e293b; border-radius: 12px; padding: 16px; position: sticky; top: 20px; max-height: calc(100vh - 120px); display: flex; flex-direction: column; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-title { font-size: 14px; font-weight: 600; }
.btn-refresh { background: none; border: none; color: #64748b; cursor: pointer; font-size: 14px; }
.empty { color: #475569; text-align: center; padding: 20px; font-size: 13px; }

.history-list { overflow-y: auto; flex: 1; }
.history-item { display: flex; gap: 10px; padding: 10px; border-bottom: 1px solid #1e293b; border-radius: 6px; }
.history-item:hover { background: #1e293b50; }
.status-icon { font-size: 16px; flex-shrink: 0; margin-top: 2px; }
.item-content { flex: 1; min-width: 0; }
.item-top { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.item-filename { font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 10px; padding: 1px 6px; border-radius: 4px; font-weight: 500; }
.badge.completed { background: #166534; color: #22c55e; }
.badge.converted { background: #1e3a5f; color: #6366f1; }
.badge.failed { background: #7f1d1d; color: #ef4444; }
.item-url { font-size: 11px; color: #64748b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 2px; }
.item-meta { font-size: 11px; color: #475569; display: flex; gap: 4px; }
.btn-delete { background: none; border: none; color: #64748b; cursor: pointer; font-size: 18px; padding: 0 4px; opacity: 0; transition: opacity 0.15s; }
.history-item:hover .btn-delete { opacity: 1; }
.btn-delete:hover { color: #ef4444; }
</style>
