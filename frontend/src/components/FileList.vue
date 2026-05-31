<template>
  <!-- 已下载文件列表 + 格式转换操作 -->
  <div class="card">
    <div class="card-header">
      <h2 class="card-title">📁 已下载文件</h2>
      <button class="btn-refresh" @click="$emit('refresh')">🔄 刷新</button>
    </div>

    <div v-if="files.length === 0" class="empty">暂无下载文件</div>

    <div class="file-list">
      <div v-for="f in files" :key="f.path" class="file-item">
        <!-- 文件信息行 -->
        <div class="file-info">
          <span class="file-icon">🎞️</span>
          <div class="file-detail">
            <span class="file-name">{{ f.name }}</span>
            <span class="file-meta">{{ f.size_mb }} MB · {{ f.format.toUpperCase() }}</span>
          </div>
        </div>

        <!-- 转换操作区 -->
        <div class="convert-bar">
          <select v-model="convertTargets[f.path]" class="fmt-select">
            <option value="">不转换</option>
            <option value="webm">WEBM</option>
            <option value="mkv">MKV</option>
            <option value="mov">MOV</option>
            <option value="avi">AVI</option>
            <option value="gif">GIF</option>
          </select>
          <select v-model="convertPresets[f.path]" class="fmt-select">
            <option value="fast">快速</option>
            <option value="medium">平衡</option>
            <option value="slow">高质量</option>
          </select>
          <label class="remove-check">
            <input v-model="convertRemove[f.path]" type="checkbox" /> 删原文件
          </label>
          <button
            class="btn-convert"
            :disabled="!convertTargets[f.path]"
            @click="onConvert(f)"
          >
            🔄 转换
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'

const props = defineProps({ files: Array })                         // 文件列表
const emit = defineEmits(['convert', 'refresh'])                     // 事件

const convertTargets = reactive({})     // { path: target_format } 映射
const convertPresets = reactive({})     // { path: preset } 映射
const convertRemove = reactive({})      // { path: boolean } 映射

function onConvert(file) {
  const fmt = convertTargets[file.path]
  if (!fmt) return
  emit('convert', {
    filePath: file.path,
    targetFormat: fmt,
    preset: convertPresets[file.path] || 'medium',
    removeOriginal: convertRemove[file.path] || false,
  })
}
</script>

<style scoped>
.card { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-title { font-size: 15px; font-weight: 600; }
.btn-refresh { background: #334155; color: #94a3b8; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.empty { color: #475569; text-align: center; padding: 24px; font-size: 13px; }

.file-item { background: #0f172a; border-radius: 8px; padding: 12px; margin-bottom: 8px; }
.file-info { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.file-icon { font-size: 24px; }
.file-detail { display: flex; flex-direction: column; }
.file-name { font-size: 13px; font-weight: 500; max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-meta { font-size: 11px; color: #64748b; margin-top: 2px; }

.convert-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.fmt-select { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px; padding: 4px 8px; font-size: 12px; outline: none; }
.remove-check { font-size: 11px; color: #94a3b8; display: flex; align-items: center; gap: 4px; white-space: nowrap; }
.btn-convert { background: #6366f1; color: #fff; border: none; padding: 5px 14px; border-radius: 6px; cursor: pointer; font-size: 12px; white-space: nowrap; }
.btn-convert:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-convert:hover:not(:disabled) { background: #5558e6; }
</style>
