// DownieClip Chrome Extension — Popup 交互脚本
// 获取当前标签页 URL 并发送到本地 Python 后端

const BACKEND_URL = 'http://localhost:8520';
const urlDisplay = document.getElementById('urlDisplay');
const btnDownload = document.getElementById('btnDownload');
const btnQueue = document.getElementById('btnQueue');
const statusEl = document.getElementById('status');
const recentList = document.getElementById('recentList');

let currentUrl = '';
let currentTabId = null;

// ── 初始化：获取当前标签页 URL ──
(async function init() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    currentUrl = tab.url || '';
    currentTabId = tab.id;
    urlDisplay.textContent = currentUrl || '（无法获取当前页面 URL）';
    btnDownload.disabled = !currentUrl.startsWith('http');
  } catch (e) {
    urlDisplay.textContent = '获取页面 URL 失败';
    btnDownload.disabled = true;
  }

  // 加载最近记录
  loadRecent();

  // 检查后端连通性
  checkBackend();
})();

// ── 下载按钮：直接发送到后端下载 ──
btnDownload.addEventListener('click', async () => {
  if (!currentUrl.startsWith('http')) return;

  btnDownload.disabled = true;
  btnDownload.textContent = '⏳ 正在提交...';
  showStatus('info', '正在连接 DownieClip...');

  try {
    const resp = await fetch(`${BACKEND_URL}/api/scrape`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: currentUrl,
        max_videos: 1,
        concurrent: 1,
        timeout: 60,
      }),
    });

    if (resp.ok) {
      const data = await resp.json();
      saveRecent(currentUrl, data.task_id);
      showStatus('success', '✅ 已发送！查看 DownieClip 进度');
    } else if (resp.status === 409) {
      showStatus('info', '⏳ 已有任务在运行，请稍后');
    } else {
      const err = await resp.json().catch(() => ({}));
      showStatus('error', `❌ 提交失败: ${err.detail || resp.status}`);
    }
  } catch (e) {
    showStatus('error', `❌ 无法连接后端 (端口 8520)`);
  }

  btnDownload.disabled = false;
  btnDownload.textContent = '⬇ 发送到 DownieClip';
});

// ── 复制按钮 ──
btnQueue.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(currentUrl);
    showStatus('info', '📋 URL 已复制到剪贴板');
  } catch (e) {
    showStatus('error', '❌ 复制失败');
  }
});

// ── 辅助函数 ──
function showStatus(type, msg) {
  statusEl.className = `status ${type}`;
  statusEl.textContent = msg;
  setTimeout(() => { statusEl.className = 'status'; }, 3000);
}

async function checkBackend() {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/health`);
    if (resp.ok) {
      const data = await resp.json();
      if (data.status === 'ok') {
        // 后端在线，无需额外提示
        return;
      }
    }
  } catch (e) {
    showStatus('error', '⚠️ DownieClip 后端未启动');
  }
}

function saveRecent(url, taskId) {
  chrome.storage.local.get({ recent: [] }, (result) => {
    const recent = result.recent || [];
    recent.unshift({ url, taskId, time: Date.now() });
    // 最多保留 10 条
    chrome.storage.local.set({ recent: recent.slice(0, 10) });
    loadRecent();
  });
}

function loadRecent() {
  chrome.storage.local.get({ recent: [] }, (result) => {
    const recent = result.recent || [];
    if (recent.length === 0) {
      recentList.innerHTML = '<span style="font-size:10px;color:#475569">暂无记录</span>';
      return;
    }
    recentList.innerHTML = recent.slice(0, 5).map(r => {
      const time = new Date(r.time);
      const timeStr = `${String(time.getHours()).padStart(2,'0')}:${String(time.getMinutes()).padStart(2,'0')}`;
      const shortUrl = r.url.replace(/^https?:\/\//, '').substring(0, 40);
      return `<div class="history-item" title="${r.url}">${timeStr} · ${shortUrl}...</div>`;
    }).join('');
  });
}

// ── 键盘快捷键 ──
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !btnDownload.disabled) {
    btnDownload.click();
  }
});
