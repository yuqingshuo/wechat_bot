/* =============================================================================
   启动控制台 · 只负责「启动 / 停止 / 运行状态」
   数据接口：/api/bot/status /api/bot/start /api/bot/stop /api/bot/save_runtime
   ============================================================================= */
'use strict';

function $(id) { return document.getElementById(id); }
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (m) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
  });
}
function setText(id, v) {
  var el = $(id);
  if (el) el.innerText = (v == null || v === '') ? '-' : v;
}
var toastTimer = null;
function toast(msg) {
  var t = $('toast');
  if (!t) return;
  t.innerText = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { t.classList.remove('show'); }, 3000);
}
async function getJSON(url) {
  var r = await fetch(url, { headers: { 'Cache-Control': 'no-cache' } });
  return r.json();
}
async function postJSON(url, body) {
  var r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {})
  });
  return r.json();
}

var S = {
  running: false,
  hasPersona: false,
  hasBrain: false,
  hasProvider: false,
  brainNeedsKey: false,
  runtimeSaving: false,
  timer: null,
  slowTimer: null
};

var STATE_UI = {
  stopped:    { pill: 'off',        text: '⚪ 没在工作',  dot: '',     state: '未启动' },
  connecting: { pill: 'connecting', text: '🟡 正在连接…', dot: 'wait', state: '正在连接微信…' },
  running:    { pill: 'on',         text: '🟢 自动工作中', dot: 'on',  state: '正在自动工作' },
  stopping:   { pill: 'connecting', text: '🟡 正在停止…', dot: 'wait', state: '正在停止…' },
  error:      { pill: 'err',        text: '🔴 出问题了',  dot: 'err',  state: '启动失败' }
};

function paintCards() {
  [['rtAutoStart', 'swAutoStart'], ['rtAutoReply', 'swAutoReply'],
   ['rtAutoMemory', 'swAutoMemory'], ['rtAutoReconnect', 'swAutoReconnect']].forEach(function (p) {
    var box = $(p[0]), card = $(p[1]);
    if (box && card) card.classList.toggle('on', !!box.checked);
  });
}

function updateTip() {
  var tip = $('runTip');
  if (!tip) return;
  if (S.running) {
    tip.innerText = '正在自动工作：回控制台打开「跟随聊天」就能看它怎么聊。';
  } else if (!S.hasProvider) {
    tip.innerText = '还没有可用的大脑：先回控制台「🧠 AI 大脑」里配置一个，再来启动。';
  } else if (S.brainNeedsKey) {
    tip.innerText = 'AI 大脑还没填密钥：回控制台「🧠 AI 大脑」点「详细设置」填好，再来启动。';
  } else if (!S.hasPersona) {
    tip.innerText = '还没有挑人设：先回控制台「🎭 挑一个人设」点一张卡片，再来启动。';
  } else {
    tip.innerText = '配置都没问题，点「启动机器人」就会自动连微信、监听、回复。';
  }
  var easy = $('btnEasy');
  if (easy) easy.disabled = S.running || !S.hasBrain || !S.hasPersona;
}

async function loadStatus() {
  try {
    var d = await getJSON('/api/bot/status');
    if (!d.ok) return;
    var ui = STATE_UI[d.state] || { pill: 'off', text: d.state_text || d.state || '未知', dot: '', state: d.state || '未知' };

    var pill = $('botStatePill');
    if (pill) { pill.className = 'bot-pill ' + ui.pill; pill.innerText = ui.text; }
    var dot = $('runDot');
    if (dot) dot.className = 'dot ' + (ui.dot || '');
    setText('runStateText', ui.state);

    var bits = [];
    bits.push(d.wx_online ? ('微信已连上' + (d.wx_nickname ? '（' + d.wx_nickname + '）' : '')) : '微信还没连上');
    if (d.listen_mode === 'whitelist') {
      var wl = d.whitelist || [];
      bits.push(wl.length ? ('只听 ' + wl.join('、')) : '监听名单还是空的');
    } else {
      bits.push('所有私聊都回');
    }
    if ((d.listen_failed || []).length) bits.push('⚠ 没听上：' + d.listen_failed.join('、'));
    if (d.last_message_at && d.last_message_from) bits.push('最近一句来自 ' + d.last_message_from);
    setText('runSub', bits.join(' ｜ '));

    setText('factUptime', d.uptime_text || '-');
    setText('factMsg', d.messages_received || 0);
    setText('factReply', d.replies_sent || 0);
    setText('factMem', d.memory_rounds || 0);
    setText('factQueue', d.queue_pending || 0);

    S.running = !!d.running;
    var busy = (d.state === 'connecting' || d.state === 'stopping');
    var bStart = $('btnStart'), bStop = $('btnStop');
    if (bStart) {
      bStart.disabled = S.running || busy;
      bStart.classList.toggle('running', S.running);
    }
    if (bStop) bStop.disabled = !S.running && !busy;

    if (!S.runtimeSaving) {
      var rt = d.runtime || {};
      if ($('rtAutoStart')) $('rtAutoStart').checked = rt.auto_start === true;
      if ($('rtAutoReply')) $('rtAutoReply').checked = rt.auto_reply !== false;
      if ($('rtAutoMemory')) $('rtAutoMemory').checked = rt.auto_save_memory !== false;
      if ($('rtAutoReconnect')) $('rtAutoReconnect').checked = rt.auto_reconnect !== false;
      if ($('rtRetry')) $('rtRetry').value = rt.connect_retry || 3;
      paintCards();
    }
    updateTip();
  } catch (e) {
    console.error('读取运行状态失败', e);
  }
}

async function loadSummary() {
  try {
    var results = await Promise.all([
      getJSON('/api/get_persona').catch(function () { return null; }),
      getJSON('/api/llm/providers').catch(function () { return null; }),
      getJSON('/api/listen/list').catch(function () { return null; })
    ]);
    var persona = results[0], prov = results[1], listen = results[2];

    var prof = (persona && persona.bot_profile) || {};
    var name = (prof.name || '').trim();
    S.hasPersona = !!name;
    setText('curPersona', name || '还没有人设（去挑一个）');

    var providers = (prov && prov.providers) || [];
    var activeId = (prov && prov.active_provider) || '';
    var active = null;
    for (var i = 0; i < providers.length; i++) {
      if ((providers[i].id || '') === activeId) { active = providers[i]; break; }
    }
    if (!active && providers.length) active = providers[0];
    S.hasProvider = !!active;
    S.brainNeedsKey = !!active && ((active.provider_type || 'openai') === 'openai' && !active.has_api_key);
    S.hasBrain = S.hasProvider && !S.brainNeedsKey;
    var brainText = active
      ? ((active.name || active.id) + ' · ' + (active.model || '未设模型') + (S.brainNeedsKey ? ' · 未填密钥' : ''))
      : '还没有配 AI 大脑';
    setText('curBrain', brainText);

    var items = (listen && listen.items) || [];
    setText('curListen', items.length ? (items.length + ' 人：' + items.map(function (x) { return x.nickname; }).join('、')) : '名单还是空的');

    updateTip();
  } catch (e) {
    console.error('读取配置摘要失败', e);
  }
}

async function loadLogs() {
  try {
    var d = await getJSON('/api/get_contacts');
    var logs = (d && d.logs) || [];
    var box = $('runLog');
    if (!box) return;
    if (!logs.length) {
      box.innerHTML = '<span class="log-empty">暂无操作记录。启动之后，收发消息、主动搭话都会记在这里。</span>';
      return;
    }
    box.innerHTML = logs.map(function (l) {
      return '<div class="' + (l.ok ? 'log-ok' : 'log-fail') + '">[' + esc(l.time) + '] ' +
        esc(l.action) + ' ➔ ' + esc(l.user_id) + '：' + esc(l.detail) + '</div>';
    }).join('');
  } catch (e) {
    console.error('读取操作记录失败', e);
  }
}

async function startBot() {
  var btn = $('btnStart');
  if (btn) { btn.disabled = true; btn.classList.add('busy'); }
  try {
    var d = await postJSON('/api/bot/start');
    if (d.ok) toast(d.msg || '收到，正在自动连微信，稍等十几秒…');
    else toast('启动失败：' + (d.msg || '未知错误'));
  } catch (e) {
    toast('启动请求失败：' + e);
  }
  if (btn) btn.classList.remove('busy');
  setTimeout(function () { loadStatus(); loadSummary(); loadLogs(); }, 1200);
}

async function stopBot() {
  var btn = $('btnStop');
  if (btn) { btn.disabled = true; btn.classList.add('busy'); }
  try {
    var d = await postJSON('/api/bot/stop');
    toast(d.msg || '已停下，不会自动回复了');
  } catch (e) {
    toast('停止失败：' + e);
  }
  if (btn) btn.classList.remove('busy');
  setTimeout(function () { loadStatus(); loadLogs(); }, 1200);
}

async function easyMode() {
  var btn = $('btnEasy');
  var old = btn ? btn.innerText : '';
  if (btn) { btn.disabled = true; btn.innerText = '检查中…'; }
  function reset() { if (btn) { btn.disabled = false; btn.innerText = old; } }
  try {
    var st = await getJSON('/api/bot/status');
    if (st && st.running) { toast('已经在自动工作中了，不用重复启动'); reset(); loadStatus(); return; }

    var missing = [];
    if (!S.hasPersona) missing.push('人设（回控制台「🎭 挑一个人设」套用一张卡）');
    if (!S.hasBrain) missing.push('AI 大脑（回控制台「🧠 AI 大脑」填好密钥）');
    if (missing.length) {
      reset();
      alert('还差一点，先完成这些：\n• ' + missing.join('\n• ') + '\n\n弄好后再点「傻瓜模式」。');
      return;
    }
    if (btn) btn.innerText = '正在启动…';
    var r1 = await postJSON('/api/bot/save_runtime', {
      auto_reply: true, auto_save_memory: true, auto_reconnect: true, connect_retry: 3
    });
    if (!r1.ok) throw new Error(r1.msg || '保存运行配置失败');
    var r2 = await postJSON('/api/bot/start');
    if (!r2.ok) throw new Error(r2.msg || '启动失败');
    toast('🚀 傻瓜模式已启动：自动连微信、自动回消息、自动存档');
    reset();
    setTimeout(function () { loadStatus(); loadSummary(); loadLogs(); }, 1500);
  } catch (e) {
    reset();
    alert('傻瓜模式出错：' + e);
  }
}

async function saveRuntime(showTip) {
  S.runtimeSaving = true;
  paintCards();
  var payload = {
    auto_start: !!($('rtAutoStart') && $('rtAutoStart').checked),
    auto_reply: !!($('rtAutoReply') && $('rtAutoReply').checked),
    auto_save_memory: !!($('rtAutoMemory') && $('rtAutoMemory').checked),
    auto_reconnect: !!($('rtAutoReconnect') && $('rtAutoReconnect').checked),
    connect_retry: parseInt(($('rtRetry') || {}).value, 10) || 3
  };
  try {
    var d = await postJSON('/api/bot/save_runtime', payload);
    if (d.ok) { if (showTip !== false) toast('✅ 运行开关已保存'); }
    else toast('保存失败：' + (d.msg || '未知错误'));
  } catch (e) {
    toast('保存失败：' + e);
  }
  S.runtimeSaving = false;
  loadStatus();
}

async function boot() {
  await Promise.all([loadSummary(), loadStatus()]);
  loadLogs();
  S.timer = setInterval(loadStatus, 3000);
  S.slowTimer = setInterval(function () { loadSummary(); loadLogs(); }, 15000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
