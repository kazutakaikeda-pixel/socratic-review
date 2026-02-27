/* ─── Phase Config ──────────────────────────────────────── */
const PHASES = {
  1: {
    name: 'Phase 1 — 作成前',
    hint: '貼り付けるもの: Notionのメモ・ブレスト・方向性をまとめたテキストなど。まだスライドになっていないもの。',
    placeholder: 'Notionの文章、ブレストメモ、方向性をまとめたテキストなどを貼り付けてください...',
  },
  2: {
    name: 'Phase 2 — 構成',
    hint: '貼り付けるもの: スライドの目次・アジェンダ・各ページのタイトルや概要。ストーリーラインがわかるもの。',
    placeholder: 'スライドの目次、アジェンダ、各ページのタイトルや概要などを貼り付けてください...',
  },
  3: {
    name: 'Phase 3 — ビジュアル',
    hint: '貼り付けるもの: 完成に近い資料のテキスト・数値・図の説明など。表現・整合性の細かいレビューをします。',
    placeholder: '各スライドのテキスト・数値・図の説明など、完成に近い資料の内容を貼り付けてください...',
  },
};

/* ─── State ─────────────────────────────────────────────── */
const state = {
  sessionId:   null,
  phase:       1,
  isStreaming: false,
};

/* ─── Phase Selection ───────────────────────────────────── */
function selectPhase(phase) {
  state.phase = phase;

  // Update step buttons
  document.querySelectorAll('.phase-step').forEach(btn => {
    btn.classList.toggle('active', parseInt(btn.dataset.phase) === phase);
  });

  // Update hint and placeholder
  const cfg = PHASES[phase];
  document.getElementById('phase-hint').textContent = cfg.hint;
  document.getElementById('doc-input').placeholder  = cfg.placeholder;
}

/* ─── Start Session ─────────────────────────────────────── */
async function startSession() {
  const docInput = document.getElementById('doc-input');
  const content  = docInput.value.trim();
  if (!content) {
    docInput.focus();
    docInput.style.borderColor = '#f09090';
    setTimeout(() => { docInput.style.borderColor = ''; }, 1500);
    return;
  }

  const btn = document.getElementById('start-btn');
  btn.disabled    = true;
  btn.textContent = '読み込み中…';

  let data;
  try {
    const res = await fetch('/api/sessions', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ document: content, phase: state.phase }),
    });
    if (!res.ok) throw new Error('Failed');
    data = await res.json();
  } catch {
    btn.disabled    = false;
    btn.textContent = 'レビューを受ける';
    alert('接続エラーが発生しました。サーバーが起動しているか確認してください。');
    return;
  }

  state.sessionId = data.session_id;

  // Switch to chat phase
  document.getElementById('input-phase').classList.remove('active');
  document.getElementById('chat-phase').classList.add('active');

  // Update header
  const meta = document.getElementById('header-meta');
  meta.classList.remove('hidden');
  document.getElementById('header-phase-badge').textContent = PHASES[state.phase].name;

  // Show opening messages
  appendReviewerMessage('maeda',    data.maeda_opening);
  appendReviewerMessage('ishikawa', data.ishikawa_opening);

  document.getElementById('msg-input').focus();
}

/* ─── Reset ─────────────────────────────────────────────── */
function resetSession() {
  state.sessionId   = null;
  state.isStreaming = false;

  document.getElementById('chat-phase').classList.remove('active');
  document.getElementById('input-phase').classList.add('active');
  document.getElementById('header-meta').classList.add('hidden');
  document.getElementById('chat-messages').innerHTML = '';
  document.getElementById('doc-input').value         = '';

  const btn = document.getElementById('start-btn');
  btn.disabled    = false;
  btn.textContent = 'レビューを受ける';

  document.getElementById('doc-input').focus();
}

/* ─── Send Message ──────────────────────────────────────── */
async function sendMessage() {
  if (state.isStreaming || !state.sessionId) return;

  const input   = document.getElementById('msg-input');
  const content = input.value.trim();
  if (!content) return;

  input.value       = '';
  input.style.height = 'auto';

  appendUserMessage(content);

  // Turn separator
  const sep = document.createElement('div');
  sep.className = 'turn-separator';
  document.getElementById('chat-messages').appendChild(sep);

  state.isStreaming = true;
  document.getElementById('send-btn').disabled = true;

  let res;
  try {
    res = await fetch(`/api/sessions/${state.sessionId}/messages`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ content }),
    });
  } catch {
    state.isStreaming = false;
    document.getElementById('send-btn').disabled = false;
    return;
  }

  // SSE state machine
  let currentReviewer  = null;
  let currentMsgEl     = null;
  let loadingEl        = null;
  let fullText         = '';

  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      let event;
      try { event = JSON.parse(line.slice(6)); } catch { continue; }

      if (event.type === 'start') {
        currentReviewer = event.reviewer;
        fullText        = '';
        loadingEl       = appendLoadingDots(currentReviewer);
        currentMsgEl    = null;

      } else if (event.type === 'token') {
        if (loadingEl) {
          loadingEl.remove();
          loadingEl    = null;
          currentMsgEl = appendReviewerMessage(event.reviewer, '');
          currentMsgEl.classList.add('streaming');
        }
        if (currentMsgEl) {
          fullText += event.content;
          const bubble = currentMsgEl.querySelector('.msg-bubble');
          bubble.textContent = fullText;
          scrollToBottom();
        }

      } else if (event.type === 'end') {
        if (currentMsgEl) {
          currentMsgEl.classList.remove('streaming');
          // Apply GOOD/MORE highlighting after streaming
          renderGoodMore(currentMsgEl.querySelector('.msg-bubble'), fullText);
        }
        currentReviewer = null;
        currentMsgEl    = null;

      } else if (event.type === 'error') {
        if (loadingEl) { loadingEl.remove(); loadingEl = null; }
        appendErrorMessage(currentReviewer);

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

/* ─── GOOD / MORE Rendering ─────────────────────────────── */
function renderGoodMore(bubbleEl, text) {
  if (!text.includes('✓ GOOD') && !text.includes('→ MORE')) return;

  const lines = text.split('\n');
  bubbleEl.innerHTML = '';

  for (const line of lines) {
    const span = document.createElement('span');
    span.style.display = 'block';

    if (line.startsWith('✓ GOOD')) {
      span.className   = 'good-line';
      span.textContent = line;
    } else if (line.startsWith('→ MORE')) {
      span.className   = 'more-line';
      span.style.marginTop = '8px';
      span.textContent = line;
    } else {
      span.textContent = line;
    }
    bubbleEl.appendChild(span);
  }
}

/* ─── DOM Helpers ───────────────────────────────────────── */
function appendReviewerMessage(reviewer, text) {
  const isM        = reviewer === 'maeda';
  const name       = isM ? '前田さん' : '石川さん';
  const avatarCls  = isM ? 'maeda-av'    : 'ishikawa-av';
  const initial    = isM ? 'M' : 'I';
  const bubbleCls  = isM ? 'maeda-bubble' : 'ishikawa-bubble';

  const el = document.createElement('div');
  el.className = 'message';
  el.innerHTML = `
    <div class="msg-avatar ${avatarCls}">${initial}</div>
    <div class="msg-body">
      <div class="msg-sender">${name}</div>
      <div class="msg-bubble ${bubbleCls}">${escapeHtml(text)}</div>
    </div>`;
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
    </div>`;
  document.getElementById('chat-messages').appendChild(el);
  scrollToBottom();
}

function appendLoadingDots(reviewer) {
  const isM       = reviewer === 'maeda';
  const avatarCls = isM ? 'maeda-av' : 'ishikawa-av';
  const initial   = isM ? 'M' : 'I';
  const name      = isM ? '前田さん' : '石川さん';

  const el = document.createElement('div');
  el.className = 'message';
  el.innerHTML = `
    <div class="msg-avatar ${avatarCls}">${initial}</div>
    <div class="msg-body">
      <div class="msg-sender">${name}</div>
      <div class="loading-bubble">
        <div class="dot"></div><div class="dot"></div><div class="dot"></div>
      </div>
    </div>`;
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
    </div>`;
  document.getElementById('chat-messages').appendChild(el);
}

function scrollToBottom() {
  const el = document.getElementById('chat-messages');
  el.scrollTop = el.scrollHeight;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ─── Event Listeners ───────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  // Initialize phase 1 hint + placeholder
  selectPhase(1);

  // Enter to send
  document.getElementById('msg-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Auto-resize textarea
  document.getElementById('msg-input').addEventListener('input', (e) => {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 150) + 'px';
  });
});
