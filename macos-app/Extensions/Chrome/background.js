// DownieClip Chrome Extension — Background Service Worker
// 右键菜单 + 键盘快捷键处理

const BACKEND_URL = 'http://localhost:8520';

// ── 安装/更新时初始化 ──
chrome.runtime.onInstalled.addListener(() => {
  // 创建右键菜单
  chrome.contextMenus.create({
    id: 'send-to-downieclip',
    title: '发送此链接到 DownieClip',
    contexts: ['link', 'page', 'video'],
  });

  chrome.contextMenus.create({
    id: 'send-page-to-downieclip',
    title: '发送当前页面到 DownieClip 下载',
    contexts: ['page'],
  });

  console.log('DownieClip Extension 已安装');
});

// ── 右键菜单点击 ──
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  let url = '';

  if (info.menuItemId === 'send-to-downieclip') {
    url = info.linkUrl || info.srcUrl || tab?.url || '';
  } else if (info.menuItemId === 'send-page-to-downieclip') {
    url = info.pageUrl || tab?.url || '';
  }

  if (url && url.startsWith('http')) {
    await sendToBackend(url);
  }
});

// ── 键盘快捷键 ──
chrome.commands.onCommand.addListener(async (command) => {
  if (command === 'send-to-downieclip') {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.url?.startsWith('http')) {
      await sendToBackend(tab.url);
    }
  }
});

// ── 发送 URL 到后端 ──
async function sendToBackend(url) {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/scrape`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: url,
        max_videos: 1,
        concurrent: 1,
        timeout: 60,
      }),
    });

    if (resp.ok) {
      const data = await resp.json();
      // 设置 Badge 显示下载中
      chrome.action.setBadgeText({ text: '⬇' });
      chrome.action.setBadgeBackgroundColor({ color: '#6366f1' });

      // 3 秒后清除 Badge
      setTimeout(() => {
        chrome.action.setBadgeText({ text: '' });
      }, 3000);

      console.log('DownieClip: 已发送', url.substring(0, 60));
    } else if (resp.status === 409) {
      chrome.action.setBadgeText({ text: '⏳' });
      setTimeout(() => chrome.action.setBadgeText({ text: '' }), 3000);
    }
  } catch (e) {
    console.warn('DownieClip: 后端连接失败', e.message);
    chrome.action.setBadgeText({ text: '❌' });
    setTimeout(() => chrome.action.setBadgeText({ text: '' }), 3000);
  }
}
