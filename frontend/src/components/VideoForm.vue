<template>
  <!-- 视频 URL 输入表单卡片（支持批量多 URL） -->
  <div class="card">
    <h2 class="card-title">📥 输入视频页面 URL（支持批量）</h2>
    <form @submit.prevent="onSubmit">
      <!-- URL 输入区 -->
      <div class="url-input-area">
        <textarea
          v-model="urlText"
          placeholder="每行一个 URL，例如：&#10;https://www.hl718.com/archives/34321&#10;https://www.hl718.com/archives/34383&#10;https://www.hl718.com/archives/34386"
          class="url-textarea"
          :disabled="disabled"
          rows="4"
        />
        <div class="url-actions">
          <span class="url-count" :class="{ 'url-over-limit': rawUrlCount > 3 }">
            {{ urls.length }} / 3 个 URL
            <span v-if="rawUrlCount > 3" class="over-limit-hint">（已截断，最多 3 个）</span>
          </span>
          <button type="button" class="btn-clear" @click="urlText = ''" :disabled="disabled || !urlText">清空</button>
        </div>
      </div>

      <!-- 提交按钮 -->
      <button type="submit" class="btn btn-primary" :disabled="disabled || urls.length === 0">
        {{ disabled ? '⏳ 运行中...' : `🔍 批量爬取 (${urls.length} 个)` }}
      </button>

      <!-- 高级选项 -->
      <details class="advanced-options">
        <summary>⚙️ 高级选项</summary>
        <div class="options-grid">
          <label class="opt">
            <span>每URL最大数量</span>
            <input v-model.number="maxVideos" type="number" min="1" max="10" class="opt-input" />
          </label>
          <label class="opt">
            <span>并发线程</span>
            <input v-model.number="concurrent" type="number" min="1" max="10" class="opt-input" />
          </label>
          <label class="opt checkbox-opt">
            <input v-model="skipHead" type="checkbox" />
            <span>跳过 HEAD 预检</span>
          </label>
          <label class="opt">
            <span>超时(秒)</span>
            <input v-model.number="timeout" type="number" min="10" max="600" class="opt-input" />
          </label>
        </div>
      </details>
    </form>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({ disabled: Boolean })
const emit = defineEmits(['start'])

const urlText = ref('')
const maxVideos = ref(1)
const concurrent = ref(1)
const skipHead = ref(false)
const timeout = ref(60)

// 原始 URL 数量（未截断）
const rawUrlCount = computed(() =>
  urlText.value.split('\n')
    .map(u => u.trim())
    .filter(u => u && (u.startsWith('http://') || u.startsWith('https://'))).length
)

// 从 textarea 中按行解析 URL 列表（最多 3 个）
const urls = computed(() =>
  urlText.value.split('\n')
    .map(u => u.trim())
    .filter(u => u && (u.startsWith('http://') || u.startsWith('https://')))
    .slice(0, 3)
)

function onSubmit() {
  if (urls.value.length === 0) return
  emit('start', {
    urls: urls.value,
    max_videos_per_url: maxVideos.value,
    concurrent: concurrent.value,
    skip_head: skipHead.value,
    timeout: timeout.value,
  })
}
</script>

<style scoped>
.card { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
.card-title { font-size: 15px; font-weight: 600; margin-bottom: 16px; }

.url-input-area { margin-bottom: 12px; }
.url-textarea {
  width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid #334155;
  background: #0f172a; color: #e2e8f0; font-size: 13px; font-family: 'Menlo', monospace;
  outline: none; resize: vertical; line-height: 1.6;
}
.url-textarea:focus { border-color: #6366f1; }
.url-textarea:disabled { opacity: 0.5; cursor: not-allowed; }

.url-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 6px; }
.url-count { font-size: 12px; color: #64748b; }
.url-count.url-over-limit { color: #f59e0b; }
.over-limit-hint { font-size: 11px; }
.btn-clear { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 12px; }

.btn { padding: 10px 24px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; font-weight: 500; width: 100%; }
.btn-primary { background: #6366f1; color: #fff; }
.btn-primary:hover { background: #5558e6; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.advanced-options { margin-top: 12px; }
.advanced-options summary { font-size: 13px; color: #94a3b8; cursor: pointer; padding: 8px 0; }
.options-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 12px 0; }
.opt { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #94a3b8; }
.checkbox-opt { flex-direction: row; align-items: center; gap: 8px; }
.opt-input { padding: 6px 10px; border-radius: 6px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; font-size: 13px; outline: none; width: 100%; }
.opt-input:focus { border-color: #6366f1; }
</style>
