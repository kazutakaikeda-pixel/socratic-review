/* ─── State ─────────────────────────────────────────────── */
const state = {
  sessionId: null,
  isStreaming: false,
};

/* ─── Start Session ─────────────────────────────────────── */
async function startSession() {
  const docInput = document.getElementById('doc-input');
  const content = docInput.value.trim();
  if (!content) {
    docInput.focus();
    docInput.style.borderColor = '#f09090';
    setTimeout(() => { docInput.style.borderColor = ''; }, 1500);
    return;
  }

  const btn = document.getElementById('start-btn');
  btn.disabled = true;
  btn.textContent = '読み込み中…';

  let data;
  try {
    const res = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document: content }),
    });
    if (!res.ok) throw new Error('Failed to create session');
    data = await res.json();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'レビューを受ける';
    alert('接続エラーが発生しました。サーバーが起動しているか確認してください。');
    return;
  }

  state.sessionId = data.session_id;

  // Switch to chat phase
  document.getElementById('input-phase').classList.remove('active');
  document.getElementById('chat-phase').classList.add('active');
  document.getElementById('header-meta').classList.remove('hidden');

  // Show opening messages from both reviewers
  appendReviewerMessage('maeda', data.maeda_opening);
  appendReviewerMessage('ishikawa', data.ishikawa_opening);

  document.getElementById('msg-input').focus();
}

/* ─── Reset ─────────────────────────────────────────────── */
function resetSession() {
  state.sessionId = null;
  state.isStreaming = false;

  document.getElementById('chat-phase').classList.remove('active');
  document.getElementById('input-phase').classList.add('active');
  document.getElementById('header-meta').classList.add('hidden');
  document.getElementById('chat-messages').innerHTML = '';
  document.getElementById('doc-input').value = '';

  const startBtn = document.getElementById('start-btn');
  startBtn.disabled = false;
  startBtn.textContent = 'レビューを受ける';

  document.getElementById('doc-input').focus();
}

/* ─── Send Message ──────────────────────────────────────── */
async function sendMessage() {
  if (state.isStreaming || !state.sessionId) return;

  const input = document.getElementById('msg-input');
  const content = input.value.trim();
  if (!content) return;

  input.value = '';
  input.style.height = 'auto';

  // Show user message
  appendUserMessage(content);

  // Add a subtle turn separator
  const sep = document.createElement('div');
  sep.className = 'turn-separator';
  document.getElementById('chat-messages').appendChild(sep);

  state.isStreaming = true;
  document.getElementById('send-btn').disabled = true;

  let res;
  try {
    res = await fetch(`/api/sessions/${state.sessionId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
  } catch (e) {
    state.isStreaming = false;
    document.getElementById('send-btn').disabled = false;
    return;
  }

  // State machine for SSE streaming
  let currentReviewer = null;
  let currentMessageEl = null;
  let loadingEl = null;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop(); // keep partial line

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      let event;
      try { event = JSON.parse(line.slice(6)); } catch { continue; }

      if (event.type === 'start') {
        currentReviewer = event.reviewer;
        // Show loading dots while waiting for first token
        loadingEl = appendLoadingDots(currentReviewer);
        currentMessageEl = null;

      } else if (event.type === 'token') {
        // First token: remove loading dots, create message bubble
        if (loadingEl) {
          loadingEl.remove();
          loadingEl = null;
          currentMessageEl = appendReviewerMessage(event.reviewer, '');
          currentMessageEl.classList.add('streaming');
        }
        if (currentMessageEl) {
          const bubble = currentMessageEl.querySelector('.msg-bubble');
          bubble.textContent += event.content;
          scrollToBottom();
        }

      } else if (event.type === 'end') {
        if (currentMessageEl) {
          currentMessageEl.classList.remove('streaming');
        }
        currentReviewer = null;
        currentMessageEl = null;

      } else if (event.type === 'error') {
        if (loadingEl) { loadingEl.remove(); loadingEl = null; }
        appendErrorMessage(event.reviewer || currentReviewer);

      } else if (event.type === 'done') {
        break;
      }
    }
  }

  state.isStreaming = false;
  document.getElementById('send-btn').disabled = false;
  document.getElementById('msg-input').focus();
  scrollToBottom();
}

/* ─── DOM Helpers ───────────────────────────────────────── */
function appendReviewerMessage(reviewer, text) {
  const isM = reviewer === 'maeda';
  const name = isM ? '前田さん' : '石川さん';
  const avatarClass = isM ? 'maeda-av' : 'ishikawa-av';
  const initial = isM ? 'M' : 'I';
  const bubbleClass = isM ? 'maeda-bubble' : 'ishikawa-bubble';

  const el = document.createElement('div');
  el.className = 'message';
  el.innerHTML = `
    <div class="msg-avatar ${avatarClass}">${initial}</div>
    <div class="msg-body">
      <div class="msg-sender">${name}</div>
      <div class="msg-bubble ${bubbleClass}">${escapeHtml(text)}</div>
    </div>
  `;
  document.getElementById('chat-messages').appendChild(el);
  scrollToBottom();
  return el;
}

function appendUserMessage(text) {
  const el = document.createElement('div');
  el.className = 'message user-msg';
  el.innerHTML = `
    <div class="msg-body" style="align-items:flex-end;display:flex;flex-direction:column;">
      <div class="msg-bubble user-bubble">${escapeHtml(text)}</div>
    </div>
  `;
  document.getElementById('chat-messages').appendChild(el);
  scrollToBottom();
}

function appendLoadingDots(reviewer) {
  const isM = reviewer === 'maeda';
  const avatarClass = isM ? 'maeda-av' : 'ishikawa-av';
  const initial = isM ? 'M' : 'I';
  const name = isM ? '前田さん' : '石川さん';

  const el = document.createElement('div');
  el.className = 'message';
  el.innerHTML = `
    <div class="msg-avatar ${avatarClass}">${initial}</div>
    <div class="msg-body">
      <div class="msg-sender">${name}</div>
      <div class="loading-bubble">
        <div class="dot"></div>
        <div class="dot"></div>
        <div class="dot"></div>
      </div>
    </div>
  `;
  document.getElementById('chat-messages').appendChild(el);
  scrollToBottom();
  return el;
}

function appendErrorMessage(reviewer) {
  const el = document.createElement('div');
  el.className = 'message';
  el.innerHTML = `
    <div class="msg-body">
      <div class="msg-bubble" style="background:#FFEBEE;color:#C62828;border-top-left-radius:4px;">
        エラーが発生しました。もう一度お試しください。
      </div>
    </div>
  `;
  document.getElementById('chat-messages').appendChild(el);
}

function scrollToBottom() {
  const el = document.getElementById('chat-messages');
  el.scrollTop = el.scrollHeight;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ─── Event Listeners ───────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  // Enter to send (Shift+Enter for newline)
  document.getElementById('msg-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Auto-resize message textarea
  document.getElementById('msg-input').addEventListener('input', (e) => {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 150) + 'px';
  });
});
