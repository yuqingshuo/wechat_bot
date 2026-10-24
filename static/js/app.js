/* =============================================================================
   微信聊天小助手 · 控制台脚本
   三个核心面板：AI 大脑 / 跟随聊天 / 挑一个人设
   数据全部走后端已有的 /api/* 接口，不引入额外依赖。
   ============================================================================= */
'use strict';

/* ---------------- 小工具 ---------------- */
function $(id) { return document.getElementById(id); }
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (m) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
  });
}
var toastTimer = null;
function toast(msg) {
  var t = $('toast');
  if (!t) return;
  t.innerText = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { t.classList.remove('show'); }, 2800);
}
function setText(id, v) {
  var el = $(id);
  if (el) el.innerText = (v == null || v === '') ? '-' : v;
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
function stageInfo(stage, force) {
  var map = {
    '1': { text: '🌱 相识', cls: 'pill-1' },
    '2': { text: '🍃 相知', cls: 'pill-2' },
    '3': { text: '❤️ 相恋', cls: 'pill-3' }
  };
  var k = String(force || stage || '1');
  return map[k] || map['1'];
}
function stageByAffection(aff) {
  return stageInfo(aff >= 80 ? '3' : (aff >= 30 ? '2' : '1'));
}

/* 第一次使用的三步引导条：人设和大模型都就绪后自动隐藏 */
function providerNeedsKey(p) {
  if (!p) return true;
  var t = p.provider_type || 'openai';
  return t === 'openai' && !p.has_api_key;
}

function updateFirstRun() {
  var el = $('firstRun'), msg = $('firstRunMsg');
  if (!el) return;
  var prof = (S.persona && S.persona.bot_profile) || {};
  var hasPersona = !!(prof.name || '').trim();
  var active = findProvider(S.activeProvider) || S.providers[0] || null;
  var hasBrain = !!active && !providerNeedsKey(active);
  var missing = [];
  if (!hasPersona) missing.push('人设');
  if (!hasBrain) missing.push('AI 大脑');
  if (!missing.length) { el.hidden = true; return; }
  el.hidden = false;
  if (msg) msg.innerText = '还差 ' + missing.join(' 和 ') + '，按下面顺序点一下就好（30 秒搞定）';
}

/* ---------------- 全局状态 ---------------- */
var S = {
  selectedUser: '',
  contacts: [],
  presets: [],
  persona: null,
  providers: [],
  activeProvider: '',
  wxOnline: false,
  listen: { mode: 'whitelist', items: [], failed: [] },
  auto: { cfg: null, targets: [] },
  chatKey: '',
  runtimeSaving: false,
  statusTimer: null,
  chatTimer: null,
  contactsTimer: null
};

var BOT_STATE_UI = {
  stopped:    { pill: 'off',        text: '⚪ 没在工作',   dot: '',     run: '未启动' },
  connecting: { pill: 'connecting', text: '🟡 正在连接…',  dot: 'wait', run: '正在连接微信…' },
  running:    { pill: 'on',         text: '🟢 自动工作中', dot: 'on',   run: '正在自动工作' },
  stopping:   { pill: 'connecting', text: '🟡 正在停止…',  dot: 'wait', run: '正在停止…' },
  error:      { pill: 'err',        text: '🔴 出问题了',   dot: 'err',  run: '启动失败' }
};

/* =============================================================================
   一、运行状态
   ============================================================================= */
async function loadBotStatus() {
  try {
    var d = await getJSON('/api/bot/status');
    if (!d.ok) return;
    var ui = BOT_STATE_UI[d.state] || { pill: 'off', text: d.state_text || d.state || '未知', dot: '', run: d.state || '未知' };

    var pill = $('botStatePill');
    if (pill) { pill.className = 'bot-pill ' + ui.pill; pill.innerText = ui.text; }

    var dot = $('runDot');
    if (dot) dot.className = 'dot ' + (ui.dot || '');
    setText('runStatus', ui.run);

    var bits = [];
    bits.push(d.wx_online ? ('微信已连上' + (d.wx_nickname ? '（' + d.wx_nickname + '）' : '')) : '微信还没连上');
    bits.push('已工作 ' + (d.uptime_text || '—'));
    if (d.listen_mode === 'whitelist') {
      var wl = d.whitelist || [];
      bits.push(wl.length ? ('只听 ' + wl.join('、')) : '监听名单还是空的');
    } else {
      bits.push('所有私聊都回');
    }
    if ((d.listen_failed || []).length) bits.push('⚠ 没听上：' + d.listen_failed.join('、'));
    if (d.last_message_at && d.last_message_from) bits.push('最近一句来自 ' + d.last_message_from);
    setText('runSub', bits.join(' ｜ '));

    setText('stMsg', d.messages_received || 0);
    setText('stReply', d.replies_sent || 0);
    setText('stMem', d.memory_rounds || 0);
    setText('stQueue', d.queue_pending || 0);

    // 「AI 大脑」底部的用量信息，让这块面板不只是一张空的切换列表
    var usage = (d.token_stats && d.token_stats.text) || '';
    if (d.last_error) usage += (usage ? ' · ' : '') + '⚠ ' + d.last_error;
    var usageEl = $('brainUsage');
    if (usageEl) {
      usageEl.innerText = usage || '还没有调用记录，聊起来这里会显示用量';
      usageEl.classList.toggle('warn', !!d.last_error);
    }

    var busy = (d.state === 'connecting' || d.state === 'stopping');
    var bStart = $('btnBotStart'), bStop = $('btnBotStop'), bEasy = $('btnEasyMode');
    if (bStart) bStart.disabled = !!d.running || busy;
    if (bStop) bStop.disabled = !d.running && !busy;
    if (bEasy) bEasy.disabled = !!d.running || busy;

    var pv = d.active_provider || {};
    var bs = $('brainState');
    if (bs) bs.innerText = d.running ? '在岗' : ((pv.id || pv.name) ? '待命' : '未配置');

    if (!S.runtimeSaving) {
      var rt = d.runtime || {};
      if ($('rtAutoStart')) $('rtAutoStart').checked = rt.auto_start === true;
      if ($('rtAutoReply')) $('rtAutoReply').checked = rt.auto_reply !== false;
      if ($('rtAutoMemory')) $('rtAutoMemory').checked = rt.auto_save_memory !== false;
      if ($('rtAutoReconnect')) $('rtAutoReconnect').checked = rt.auto_reconnect !== false;
      if ($('rtRetry')) $('rtRetry').value = rt.connect_retry || 3;
      paintSwitches();
    }
  } catch (e) {
    console.error('读取运行状态失败', e);
  }
}

function paintSwitches() {
  [['rtAutoStart', 'swAutoStart'], ['rtAutoReply', 'swAutoReply'],
   ['rtAutoMemory', 'swAutoMemory'], ['rtAutoReconnect', 'swAutoReconnect'],
   ['autoEnabled', 'swAutoChat']].forEach(function (p) {
    var box = $(p[0]), card = $(p[1]);
    if (box && card) card.classList.toggle('on', !!box.checked);
  });
}

async function startBot() {
  var btn = $('btnBotStart');
  if (btn) { btn.disabled = true; btn.innerText = '正在连接…'; }
  var pill = $('botStatePill');
  if (pill) { pill.className = 'bot-pill connecting'; pill.innerText = '🟡 正在连接…'; }
  try {
    var d = await postJSON('/api/bot/start');
    toast(d.msg || '收到，正在自动连微信，稍等十几秒…');
  } catch (e) {
    alert('启动失败：' + e);
  }
  if (btn) btn.innerText = '🚀 启动';
  loadBotStatus();
}

async function stopBot() {
  var btn = $('btnBotStop');
  if (btn) btn.disabled = true;
  try {
    var d = await postJSON('/api/bot/stop');
    toast(d.msg || '已停下，不会自动回复了');
  } catch (e) {
    alert('停止失败：' + e);
  }
  loadBotStatus();
  loadAutoChat();
}

async function saveRuntime(showTip) {
  S.runtimeSaving = true;
  paintSwitches();
  var payload = {
    auto_start: !!($('rtAutoStart') && $('rtAutoStart').checked),
    auto_reply: !!($('rtAutoReply') && $('rtAutoReply').checked),
    auto_save_memory: !!($('rtAutoMemory') && $('rtAutoMemory').checked),
    auto_reconnect: !!($('rtAutoReconnect') && $('rtAutoReconnect').checked),
    connect_retry: parseInt(($('rtRetry') || {}).value, 10) || 3
  };
  try {
    var d = await postJSON('/api/bot/save_runtime', payload);
    if (d.ok) { if (showTip !== false) toast('✅ 运行设置已保存'); }
    else alert('保存失败：' + (d.msg || '未知错误'));
  } catch (e) {
    alert('保存失败：' + e);
  }
  S.runtimeSaving = false;
  loadBotStatus();
}

async function easyMode() {
  var btn = $('btnEasyMode');
  var old = btn ? btn.innerText : '🤖 傻瓜模式';
  if (btn) { btn.disabled = true; btn.innerText = '检查中…'; }
  function reset() { if (btn) { btn.disabled = false; btn.innerText = old; } }

  try {
    var st = null;
    try { st = await getJSON('/api/bot/status'); } catch (e) {}
    if (st && st.running) { toast('✅ 已经在自动工作中了，不用重复启动'); loadBotStatus(); reset(); return; }

    var persona = null;
    try { persona = await getJSON('/api/persona_presets'); } catch (e) {}
    var prov = null;
    try { prov = await getJSON('/api/llm/providers'); } catch (e) {}

    var missing = [];
    if (!(persona && persona.current_name)) missing.push('人设（在「挑一个人设」里套用一个，或自己填好保存）');
    if (!(prov && prov.active_provider)) missing.push('AI 大脑（在「AI 大脑」里配置并激活一个模型）');
    if (missing.length) {
      reset();
      alert('还差一点，先完成这些：\n• ' + missing.join('\n• ') + '\n\n弄好后再点「傻瓜模式」，它会全自动启动。');
      return;
    }

    var r1 = await postJSON('/api/bot/save_runtime', {
      auto_reply: true, auto_save_memory: true, auto_reconnect: true, connect_retry: 3
    });
    if (!r1.ok) throw new Error(r1.msg || '保存运行配置失败');

    var r2 = await postJSON('/api/bot/start');
    if (!r2.ok) throw new Error(r2.msg || '启动失败');
    toast('🚀 傻瓜模式已启动：自动连微信、自动回消息、自动存档');
    reset();
    loadBotStatus();
  } catch (e) {
    reset();
    alert('傻瓜模式出错：' + e);
  }
}

/* =============================================================================
   二、AI 大脑
   ============================================================================= */
async function loadLLM() {
  var st = $('llmStatus');
  try {
    var d = await getJSON('/api/llm/providers');
    if (!d.ok) { if (st) st.innerText = '读不到大脑列表'; return; }
    S.providers = d.providers || [];
    S.activeProvider = d.active_provider || '';
    renderBrain();
    renderLLMSelect();
    fillLLMForm(S.activeProvider);
    updateFirstRun();
  } catch (e) {
    if (st) st.innerText = '读取失败：' + e;
  }
}

function findProvider(id) {
  for (var i = 0; i < S.providers.length; i++) {
    var p = S.providers[i];
    if ((p.id || p.provider_id) === id) return p;
  }
  return null;
}

function renderBrain() {
  var p = findProvider(S.activeProvider) || S.providers[0] || {};
  var pid = p.id || p.provider_id || '';
  setText('brainName', p.name || pid || '还没配置');
  setText('brainModel', p.model || '未设模型');
  setText('brainTemp', p.temperature == null ? '默认' : p.temperature);
  setText('brainKey', p.has_api_key ? (p.api_key_source === 'env' ? '环境变量' : '已配置') : '未配置');

  var box = $('brainQuickList');
  if (!box) return;
  if (!S.providers.length) {
    box.innerHTML = '<div class="empty-mini">还没有可用的大脑，点右上角「详细设置」添加一个。</div>';
    var foot0 = $('brainFoot');
    if (foot0) foot0.innerText = '还没有可用的大脑，点「详细设置」添加一个';
    updateFirstRun();
    return;
  }
  box.innerHTML = '';
  S.providers.forEach(function (it) {
    var id = it.id || it.provider_id || '';
    var on = id === S.activeProvider;
    var row = document.createElement('div');
    row.className = 'brain-item' + (on ? ' on' : '');
    row.title = (it.base_url || '') + '\n点击切换到这个大脑';
    row.innerHTML =
      '<span class="bi-dot"></span>' +
      '<span class="bi-name">' + esc(it.name || id) + '</span>' +
      '<span class="bi-model">' + esc(it.model || '未设模型') + '</span>';
    row.onclick = function () { switchProvider(id); };
    box.appendChild(row);
  });

  var foot = $('brainFoot');
  if (foot) {
    foot.innerText = providerNeedsKey(p)
      ? '⚠ 还没填密钥：点「详细设置」填好保存，立刻就能用'
      : '换完立刻生效，不用重启 · 密钥不会显示在页面上';
  }
  updateFirstRun();
}

function renderLLMSelect() {
  var sel = $('llmSelect');
  if (!sel) return;
  sel.innerHTML = '';
  S.providers.forEach(function (p) {
    var pid = p.id || p.provider_id || '';
    var o = document.createElement('option');
    o.value = pid;
    o.innerText = (p.name || pid) + '（' + (p.model || '未设模型') + '）';
    if (pid === S.activeProvider) o.selected = true;
    sel.appendChild(o);
  });
  var st = $('llmStatus');
  if (st) {
    var cur = findProvider(S.activeProvider);
    st.innerText = cur ? ('当前：' + (cur.name || cur.id)) : '';
  }
}

function fillLLMForm(activeId) {
  var p = findProvider(activeId) || S.providers[0] || {};
  if ($('llmName')) $('llmName').value = p.name || '';
  if ($('llmBaseUrl')) $('llmBaseUrl').value = p.base_url || '';
  if ($('llmModel')) $('llmModel').value = p.model || '';
  if ($('llmTemp')) $('llmTemp').value = (p.temperature == null ? '' : p.temperature);

  var ak = $('llmApiKey');
  if (ak) {
    ak.value = '';
    var src = p.api_key_source || (p.has_api_key ? 'saved' : 'none');
    var txt = {
      env: '已配置（来自环境变量，留空不修改）',
      config_local: '已配置（来自 config_local.py，留空不修改）',
      saved: '已配置（留空表示不修改）',
      none: 'sk-…'
    };
    ak.placeholder = txt[src] || txt.saved;
  }
  var hint = $('llmKeyHint');
  if (hint) {
    var src2 = p.api_key_source || '';
    if (src2 === 'env' || src2 === 'config_local') {
      hint.innerText = '🔒 密钥来自' + (src2 === 'env' ? '环境变量' : 'config_local.py') + '，优先级更高，这里填了也不生效';
      hint.style.display = 'block';
    } else if (src2 === 'saved') {
      hint.innerText = '🔒 密钥已存在服务端，不会显示在页面上；留空即保持不变';
      hint.style.display = 'block';
    } else {
      hint.innerText = '';
      hint.style.display = 'none';
    }
  }
}

async function switchProvider(id) {
  if (!id || id === S.activeProvider) return;
  try {
    var d = await postJSON('/api/llm/switch', { provider_id: id });
    if (d.ok) {
      S.activeProvider = id;
      toast('🧠 已切换大脑，立刻生效');
      renderBrain();
      renderLLMSelect();
      fillLLMForm(id);
      updateFirstRun();
      loadBotStatus();
    } else {
      alert('切换失败：' + (d.msg || '未知错误'));
    }
  } catch (e) {
    alert('切换失败：' + e);
  }
}

async function switchLLM() {
  var sel = $('llmSelect');
  if (sel && sel.value) await switchProvider(sel.value);
}

async function saveLLM() {
  var sel = $('llmSelect');
  var id = sel ? sel.value : '';
  if (!id) { toast('列表还没读出来，稍等两秒再点'); return; }
  var t = ($('llmTemp') || {}).value || '';
  var payload = {
    id: id,
    name: (($('llmName') || {}).value || '').trim(),
    base_url: (($('llmBaseUrl') || {}).value || '').trim(),
    api_key: (($('llmApiKey') || {}).value || '').trim(),
    model: (($('llmModel') || {}).value || '').trim()
  };
  if (t.trim() !== '') payload.temperature = parseFloat(t);
  try {
    var d = await postJSON('/api/llm/save_provider', payload);
    if (d.ok) { toast('✅ 大脑设置已保存'); loadLLM(); }
    else alert('保存失败：' + (d.msg || '未知错误'));
  } catch (e) {
    alert('保存失败：' + e);
  }
}

/* =============================================================================
   三、人设
   ============================================================================= */
async function loadPersona() {
  try {
    var d = await getJSON('/api/get_persona');
    S.persona = d;
    fillPersonaFields(d);
    renderPersonaPanel();
    renderUsers(d.users || {});
    renderPromptView();
    updateFirstRun();
  } catch (e) {
    console.error('加载人设失败', e);
  }
}

function currentPreset() {
  var prof = (S.persona && S.persona.bot_profile) || {};
  for (var i = 0; i < S.presets.length; i++) {
    if (S.presets[i].is_current) return S.presets[i];
  }
  for (var j = 0; j < S.presets.length; j++) {
    if ((S.presets[j].bot_profile || {}).name === prof.name) return S.presets[j];
  }
  return null;
}

function renderPersonaPanel() {
  var prof = (S.persona && S.persona.bot_profile) || {};
  var cur = currentPreset();
  var hasName = !!(prof.name || '').trim();
  setText('personaEmoji', (cur && cur.emoji) ? cur.emoji : '🎭');
  setText('personaName', hasName ? prof.name : '还没有人设');
  setText('personaIdentity', hasName
    ? (prof.identity || '还没设身份')
    : '点下面任一张卡片就能用');
  setText('personaTag', hasName
    ? ((cur && cur.tagline) ? cur.tagline : ((prof.base_personality || '').slice(0, 40) || '还没写性格'))
    : '推荐先套用一套预设，最快');
  var nameEl = $('personaName');
  if (nameEl) nameEl.classList.toggle('empty', !hasName);

  var box = $('personaStage');
  if (!box) return;
  var stages = (S.persona && S.persona.stages) || {};
  var meta = [
    { k: '1', icon: '🌱', name: '相识' },
    { k: '2', icon: '🍃', name: '相知' },
    { k: '3', icon: '❤️', name: '相恋' }
  ];
  box.innerHTML = meta.map(function (m) {
    var s = stages[m.k] || {};
    return '<div class="stage-mini"><b>' + m.icon + ' ' + m.name + '</b><span>' +
      esc(s.description || '（还没写）') + '</span></div>';
  }).join('');
}

async function loadPresets() {
  try {
    var d = await getJSON('/api/persona_presets');
    if (!d.ok) return;
    S.presets = d.presets || [];
    renderPersonaChips();
    renderPresetGrid();
    renderPersonaPanel();
  } catch (e) {
    console.error('读取人设列表失败', e);
  }
}

function renderPersonaChips() {
  var box = $('personaChips');
  if (!box) return;
  if (!S.presets.length) {
    box.innerHTML = '<div class="empty-mini">还没有预设人设，点右上角「自己改」手写一个。</div>';
    return;
  }
  box.innerHTML = '';
  S.presets.forEach(function (p) {
    var on = !!p.is_current;
    var el = document.createElement('div');
    el.className = 'persona-chip' + (on ? ' on' : '');
    el.title = (p.intro || '') + '\n\n' + (p.disclaimer || '');
    el.innerHTML =
      '<span class="pc-emoji">' + esc(p.emoji || '🎭') + '</span>' +
      '<span class="pc-name">' + esc(p.nick || p.id) + '</span>' +
      '<span class="pc-tag">' + esc(p.tagline || '') + '</span>' +
      (on ? '<span class="pc-on">正在用</span>' : '');
    el.onclick = function () { applyPreset(p); };
    box.appendChild(el);
  });
}

function renderPresetGrid() {
  var g = $('presetGrid');
  if (!g) return;
  if (!S.presets.length) {
    g.innerHTML = '<div class="empty-mini">还没有预设人设。</div>';
    return;
  }
  g.innerHTML = '';
  S.presets.forEach(function (p) {
    var c = document.createElement('div');
    c.className = 'preset-card' + (p.is_current ? ' on' : '');
    var ident = ((p.bot_profile || {}).identity || '').split('/')[0].trim();
    c.innerHTML =
      '<div class="preset-emoji">' + esc(p.emoji || '🎭') + '</div>' +
      '<div class="preset-nick">' + esc(p.nick || p.id) + '</div>' +
      '<div class="preset-tag">' + esc(p.tagline || '') + '</div>' +
      '<div class="preset-job">' + esc(ident) + '</div>' +
      '<div class="preset-fict">虚构人设 · 不对应任何真实个人</div>' +
      (p.is_current ? '<div class="preset-on">正在用</div>' : '');
    c.title = (p.intro || '') + '\n\n' + ((p.bot_profile || {}).base_personality || '') +
      (p.disclaimer ? '\n\n' + p.disclaimer : '');
    c.onclick = function () { applyPreset(p); };
    g.appendChild(c);
  });
}

async function applyPreset(p) {
  var ok = confirm('切换成「' + (p.nick || p.id) + '」？\n\n会覆盖现在的名字、身份、性格和三段提示词。\n（你自己改过的内容会被替换掉）\n\n提示：这套人设是虚构创作，不对应任何真实个人。');
  if (!ok) return;
  try {
    var d = await postJSON('/api/apply_persona_preset', { preset_id: p.id });
    if (!d.ok) { alert('切换失败：' + (d.msg || '未知错误')); return; }
    toast('✨ 已换成「' + (d.nick || p.nick) + '」');
    await loadPersona();
    await loadPresets();
  } catch (e) {
    alert('切换失败：' + e);
  }
}

function fillPersonaFields(d) {
  var prof = (d && d.bot_profile) || {};
  var stages = (d && d.stages) || {};
  var map = {
    botName: prof.name, botIdentity: prof.identity, botAge: prof.age,
    botGender: prof.gender, basePersonality: prof.base_personality,
    stageDesc1: (stages['1'] || {}).description, stagePrompt1: (stages['1'] || {}).prompt,
    stageDesc2: (stages['2'] || {}).description, stagePrompt2: (stages['2'] || {}).prompt,
    stageDesc3: (stages['3'] || {}).description, stagePrompt3: (stages['3'] || {}).prompt
  };
  Object.keys(map).forEach(function (id) {
    var el = $(id);
    if (el && document.activeElement !== el) el.value = map[id] || '';
  });
}

async function saveAllSettings() {
  var payload = {
    bot_profile: {
      name: (($('botName') || {}).value || '').trim(),
      identity: (($('botIdentity') || {}).value || '').trim(),
      age: (($('botAge') || {}).value || '').trim(),
      gender: (($('botGender') || {}).value || '').trim(),
      base_personality: (($('basePersonality') || {}).value || '').trim()
    },
    stages: {
      '1': { description: (($('stageDesc1') || {}).value || '').trim(), prompt: (($('stagePrompt1') || {}).value || '').trim() },
      '2': { description: (($('stageDesc2') || {}).value || '').trim(), prompt: (($('stagePrompt2') || {}).value || '').trim() },
      '3': { description: (($('stageDesc3') || {}).value || '').trim(), prompt: (($('stagePrompt3') || {}).value || '').trim() }
    }
  };
  try {
    var d = await postJSON('/api/save_persona', payload);
    if (d.ok) {
      toast('✨ 人设已保存，立刻生效');
      await loadPersona();
      await loadPresets();
    } else {
      alert('保存失败：' + (d.msg || '未知错误'));
    }
  } catch (e) {
    alert('保存请求失败：' + e);
  }
}

function renderPromptView() {
  var box = $('promptView');
  if (!box) return;
  var d = S.persona || {};
  var prof = d.bot_profile || {};
  var stages = d.stages || {};
  var meta = { '1': ['🌱 相识', '0~29'], '2': ['🍃 相知', '30~79'], '3': ['❤️ 相恋', '80+'] };
  var html = '<div class="pv-box"><div class="pv-name">📜 当前生效的提示词' +
    (prof.name ? ' · ' + esc(prof.name) : '') + '</div>' +
    '<div class="pv-desc">' + esc(prof.base_personality || '还没写性格') + '</div>';
  ['1', '2', '3'].forEach(function (k) {
    var s = stages[k] || {};
    html += '<div class="pv-name" style="margin-top:14px">' + meta[k][0] +
      '<span class="stage-threshold">' + meta[k][1] + '</span></div>' +
      '<div class="pv-desc">' + esc(s.description || '') + '</div>' +
      '<div class="pv-text">' + esc(s.prompt || '（空）') + '</div>';
  });
  box.innerHTML = html + '</div>';
}

/* =============================================================================
   四、跟随聊天
   ============================================================================= */
async function loadContacts() {
  try {
    var d = await getJSON('/api/get_contacts');
    if (!d.ok) return;
    S.wxOnline = !!d.wx_online;
    S.contacts = d.contacts || [];
    renderChatPicker();
    renderLogs(d.logs || []);
    if (S.selectedUser) refreshChatHeader();
  } catch (e) {
    console.error('加载好友列表失败', e);
  }
}

function avatarChar(name) {
  var s = String(name || '?').trim();
  return s ? s.slice(0, 1) : '?';
}

function renderChatPicker() {
  var box = $('chatPicker');
  if (!box) return;
  if (!S.contacts.length) {
    box.innerHTML = S.wxOnline
      ? '<div class="empty-mini">微信已经连上，但还没有能聊的好友：展开下面的「监听好友」加一个，或者等它连上后刷新。</div>'
      : '<div class="empty-mini">微信还没连上：先点下面运行条上的「🚀 启动」，连上之后这里会出现好友。</div>';
    return;
  }
  box.innerHTML = '';
  S.contacts.forEach(function (c) {
    var uid = c.user_id || '';
    var on = uid === S.selectedUser;
    var el = document.createElement('div');
    el.className = 'chat-chip' + (on ? ' on' : '');
    el.title = uid + ' · 好感 ' + (c.affection || 0) + ' · 已聊 ' + (c.chat_count || 0) + ' 轮';
    el.innerHTML =
      '<span class="cc-avatar">' + esc(avatarChar(uid)) + '</span>' +
      '<span class="cc-name">' + esc(uid) + '</span>' +
      '<span class="cc-badge">' + (c.affection || 0) + '°</span>';
    el.onclick = function () { selectContact(uid); };
    box.appendChild(el);
  });
}

function selectContact(uid) {
  S.selectedUser = uid;
  S.chatKey = '';
  renderChatPicker();
  refreshChatHeader();
  if ($('btnSend')) $('btnSend').disabled = false;
  ['btnGen', 'btnGenSend'].forEach(function (id) { if ($(id)) $(id).disabled = false; });
  loadChatStream(true);
  loadMind();
  refreshAutoChatBtn();
}

function refreshChatHeader() {
  var c = null;
  for (var i = 0; i < S.contacts.length; i++) {
    if (S.contacts[i].user_id === S.selectedUser) { c = S.contacts[i]; break; }
  }
  if (!S.selectedUser) { setText('chatTarget', '还没选好友'); return; }
  var s = c && c.force_stage ? stageInfo(null, c.force_stage) : stageByAffection((c && c.affection) || 0);
  setText('chatTarget', S.selectedUser);
  var pill = $('chatStage');
  if (pill) { pill.className = 'stage-pill ' + s.cls; pill.innerText = s.text; }
  setText('chatMeta', c ? ('好感 ' + (c.affection || 0) + ' 分 · 已聊 ' + (c.chat_count || 0) + ' 轮') : '');
}

async function loadChatStream(force) {
  var box = $('chatStream');
  if (!box || !S.selectedUser) return;
  try {
    var d = await getJSON('/api/chat/stream?user_id=' + encodeURIComponent(S.selectedUser) + '&limit=40');
    if (!d.ok) return;

    var msgs = d.messages || [];
    var key = S.selectedUser + '|' + msgs.length + '|' + (msgs.length ? msgs[msgs.length - 1].text : '');
    if (!force && key === S.chatKey) return;
    S.chatKey = key;

    var src = $('chatSource');
    if (src) {
      src.innerText = d.source === 'wechat' ? '● 微信实时记录'
        : (d.source === 'memory' ? '● 来自机器人记忆' : '');
    }

    if (!msgs.length) {
      box.innerHTML =
        '<div class="chat-empty"><div class="chat-empty-icon">💤</div>' +
        '<div class="chat-empty-title">还没有聊天记录</div>' +
        '<div class="chat-empty-sub">等它开口，或者你在下面先发一句</div></div>';
      return;
    }

    var nearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 80;
    box.innerHTML = msgs.map(function (m) {
      var who = m.role === 'bot' ? 'bot' : 'friend';
      return '<div class="msg ' + who + '">' +
        '<div class="msg-avatar">' + esc(who === 'bot' ? 'AI' : avatarChar(S.selectedUser)) + '</div>' +
        '<div class="msg-body"><div class="msg-text">' + esc(m.text) + '</div>' +
        (m.time ? '<div class="msg-time">' + esc(m.time) + '</div>' : '') +
        '</div></div>';
    }).join('');

    if (force || nearBottom) {
      requestAnimationFrame(function () { box.scrollTop = box.scrollHeight; });
    }
  } catch (e) {
    console.error('读取聊天流水失败', e);
  }
}

async function sendSelectedMessage() {
  if (!S.selectedUser) { toast('先在上面点一个好友'); return; }
  var input = $('messageInput');
  var message = input ? input.value.trim() : '';
  if (!message) { toast('先在输入框里写一句话'); return; }

  var btn = $('btnSend');
  if (btn) { btn.disabled = true; btn.innerText = '发送中…'; }
  try {
    var d = await postJSON('/api/send_message', {
      user_id: S.selectedUser,
      message: message,
      humanlike: !!($('humanlikeChk') && $('humanlikeChk').checked),
      count_affection: !!($('affectionChk') && $('affectionChk').checked)
    });
    if (d.ok) {
      toast('✅ 已发送');
      if (input) input.value = '';
      setTimeout(function () { loadChatStream(true); loadContacts(); }, 1200);
    } else {
      alert('发送失败：' + (d.msg || '未知错误'));
    }
  } catch (e) {
    alert('发送请求失败：' + e);
  }
  if (btn) { btn.disabled = false; btn.innerText = '发送'; }
}

async function aiOutreach(doSend) {
  if (!S.selectedUser) { toast('先在上面点一个好友'); return; }
  var btn = $(doSend ? 'btnGenSend' : 'btnGen');
  var old = btn ? btn.innerText : '';
  if (btn) { btn.disabled = true; btn.innerText = 'AI 正在想…'; }
  try {
    var d = await postJSON('/api/ai_outreach', {
      user_id: S.selectedUser,
      topic: (($('topicInput') || {}).value || '').trim(),
      send: !!doSend,
      count_affection: !!($('affectionChk') && $('affectionChk').checked)
    });
    if (!d.ok) { alert('生成失败：' + (d.msg || '未知错误')); return; }
    if ($('messageInput')) $('messageInput').value = d.message || '';
    toast(d.sent ? '💌 已经发出去了' : '✍️ 写好了，满意就点「发送」');
    setTimeout(function () { loadChatStream(true); loadContacts(); }, 1200);
  } catch (e) {
    alert('请求失败：' + e);
  }
  if (btn) { btn.disabled = false; btn.innerText = old; }
}

function toggleChatExpand() {
  var panel = $('panelChat');
  var btn = $('btnChatExpand');
  if (!panel) return;
  var on = panel.classList.toggle('expanded');
  document.body.classList.toggle('chat-locked', on);
  if (btn) btn.innerText = on ? '收起' : '放大';
  setTimeout(function () { loadChatStream(true); }, 60);
}

/* =============================================================================
   五、自动聊天（跟着某个人持续聊）
   ============================================================================= */
async function loadAutoChat() {
  try {
    var d = await getJSON('/api/get_auto_chat');
    if (!d.ok) return;
    var cfg = d.config || {};
    var st = d.status || {};
    S.auto.cfg = cfg;
    S.auto.targets = st.targets || cfg.targets || [];

    if ($('autoEnabled') && document.activeElement !== $('autoEnabled')) $('autoEnabled').checked = !!cfg.enabled;
    if ($('autoInterval')) $('autoInterval').value = cfg.interval_minutes || 60;
    if ($('autoMax')) $('autoMax').value = cfg.max_per_day || 20;
    if ($('autoStart')) $('autoStart').value = (cfg.active_start == null ? 9 : cfg.active_start);
    if ($('autoEnd')) $('autoEnd').value = (cfg.active_end == null ? 23 : cfg.active_end);
    if ($('autoJitter')) $('autoJitter').checked = cfg.jitter !== false;
    if ($('autoAffection')) $('autoAffection').checked = cfg.count_affection !== false;
    if ($('autoTopics') && document.activeElement !== $('autoTopics')) $('autoTopics').value = cfg.topics || '';

    var s = $('autoStatus');
    if (s) {
      s.innerText = (cfg.enabled ? '🟢 已开启' : '⚪ 已关闭') +
        ' ｜ 每 ' + (cfg.interval_minutes || 60) + ' 分钟一次' +
        ' ｜ 活跃 ' + (cfg.active_start == null ? 9 : cfg.active_start) + ':00-' + (cfg.active_end == null ? 23 : cfg.active_end) + ':00' +
        ' ｜ 今天已说 ' + (st.count_today || 0) + ' / ' + (st.max_per_day || cfg.max_per_day || 20) + ' 句' +
        ' ｜ 目标 ' + (S.auto.targets.length || 0) + ' 人' +
        (st.reason ? (' ｜ ' + st.reason) : '');
    }
    paintSwitches();
    renderAutoTargetChips();
    refreshAutoChatBtn();
  } catch (e) {
    console.error('读取主动聊天失败', e);
  }
}

function renderAutoTargetChips() {
  var box = $('autoTargetChips');
  if (!box) return;
  var names = S.contacts.map(function (c) { return c.user_id; });
  S.auto.targets.forEach(function (t) { if (names.indexOf(t) < 0) names.push(t); });
  if (!names.length) {
    box.innerHTML = '<span class="empty-mini">好友列表还没读到，连上微信后这里会出现人名。</span>';
    return;
  }
  box.innerHTML = '';
  names.forEach(function (n) {
    var on = S.auto.targets.indexOf(n) >= 0;
    var chip = document.createElement('span');
    chip.className = 't-chip' + (on ? ' on' : '');
    chip.innerText = (on ? '✅ ' : '○ ') + n;
    chip.onclick = function () { toggleAutoTarget(n, !on); };
    box.appendChild(chip);
  });
}

async function postAutoChat(payload, okText) {
  try {
    var d = await postJSON('/api/save_auto_chat', payload);
    if (!d.ok) { alert('保存失败：' + (d.msg || '未知错误')); return; }
    if (d.status && d.status.targets) S.auto.targets = d.status.targets;
    toast('✅ ' + okText);
    await loadAutoChat();
  } catch (e) {
    alert('请求失败：' + e);
  }
}

function toggleAutoTarget(name, on) {
  var next = S.auto.targets.slice();
  var i = next.indexOf(name);
  if (on && i < 0) next.push(name);
  if (!on && i >= 0) next.splice(i, 1);
  S.auto.targets = next;
  renderAutoTargetChips();
  postAutoChat({ targets: next }, '主动聊天名单已更新');
}

function collectAutoForm() {
  return {
    enabled: !!($('autoEnabled') && $('autoEnabled').checked),
    interval_minutes: parseInt(($('autoInterval') || {}).value || '60', 10),
    active_start: parseInt(($('autoStart') || {}).value || '9', 10),
    active_end: parseInt(($('autoEnd') || {}).value || '23', 10),
    max_per_day: parseInt(($('autoMax') || {}).value || '20', 10),
    jitter: !!($('autoJitter') && $('autoJitter').checked),
    count_affection: !!($('autoAffection') && $('autoAffection').checked),
    topics: (($('autoTopics') || {}).value || ''),
    targets: S.auto.targets
  };
}

async function saveAutoChat() {
  var f = collectAutoForm();
  await postAutoChat(f, f.enabled ? ('已打开：每 ' + f.interval_minutes + ' 分钟主动说一句') : '已保存（当前是关闭状态）');
}

async function onAutoEnabledChange() {
  var on = !!($('autoEnabled') && $('autoEnabled').checked);
  paintSwitches();
  await postAutoChat({ enabled: on, targets: S.auto.targets }, on ? '已打开，时间一到它自己就会去说话' : '已关闭，它不会再主动开口');
}

async function autoChatNow() {
  var btn = $('btnAutoNow');
  var old = btn ? btn.innerText : '';
  if (btn) { btn.disabled = true; btn.innerText = '正在说…'; }
  try {
    var d = await postJSON('/api/auto_chat_now');
    toast(d.ok ? ('▶️ ' + d.msg) : ('没说成：' + (d.msg || '未知原因')));
    setTimeout(function () { loadContacts(); loadChatStream(true); }, 2500);
  } catch (e) {
    alert('请求失败：' + e);
  }
  if (btn) { btn.disabled = false; btn.innerText = old; }
}

function refreshAutoChatBtn() {
  var btn = $('btnAutoChat');
  if (!btn) return;
  if (!S.selectedUser) {
    btn.disabled = true;
    btn.classList.remove('on');
    btn.innerText = '🤖 自动聊天';
    return;
  }
  var on = !!(S.auto.cfg && S.auto.cfg.enabled && (S.auto.targets || []).indexOf(S.selectedUser) >= 0);
  btn.disabled = false;
  btn.classList.toggle('on', on);
  btn.innerText = on ? '⏹ 停止自动聊天' : '🤖 自动聊天';
  btn.title = on ? ('正在自动陪聊 ' + S.selectedUser + '，点一下停止') : ('让 AI 持续主动陪 ' + S.selectedUser + ' 聊天');
}

async function toggleAutoChatWith() {
  if (!S.selectedUser) { toast('先点一个好友'); return; }
  var on = !!(S.auto.cfg && S.auto.cfg.enabled && (S.auto.targets || []).indexOf(S.selectedUser) >= 0);
  if (!on) {
    var next = S.auto.targets.slice();
    if (next.indexOf(S.selectedUser) < 0) next.push(S.selectedUser);
    S.auto.targets = next;
    await postAutoChat({ enabled: true, targets: next }, '已开启：它会持续主动找 ' + S.selectedUser + ' 聊');
  } else {
    var next2 = S.auto.targets.filter(function (x) { return x !== S.selectedUser; });
    S.auto.targets = next2;
    await postAutoChat({ targets: next2 }, '已停止陪 ' + S.selectedUser + ' 聊天');
  }
  refreshAutoChatBtn();
}

/* =============================================================================
   六、监听好友
   ============================================================================= */
function addListenRow(nick, failed) {
  var box = $('listenRows');
  if (!box) return;
  var row = document.createElement('div');
  row.className = 'listen-row';
  row.innerHTML =
    '<input type="text" class="lstNick" value="' + esc(nick || '') + '" placeholder="微信昵称 / 备注（和通讯录一模一样）">' +
    (failed ? '<span class="listen-fail">❌ 没听上</span>' : '') +
    '<button class="row-del" type="button" title="删除这一行">✕</button>';
  row.querySelector('.row-del').onclick = function () { row.remove(); };
  box.appendChild(row);
}

async function loadListen() {
  try {
    var d = await getJSON('/api/listen/list');
    if (!d.ok) return;
    S.listen.mode = d.mode || 'whitelist';
    S.listen.items = d.items || [];
    S.listen.failed = d.listen_failed || [];

    if ($('listenMode')) $('listenMode').value = S.listen.mode;
    var box = $('listenRows');
    if (box) box.innerHTML = '';
    S.listen.items.forEach(function (it) { addListenRow(it.nickname, S.listen.failed.indexOf(it.nickname) >= 0); });
    if (!S.listen.items.length) addListenRow('', false);

    var st = $('listenStatus');
    if (st) st.innerText = (d.store_file || 'listen_list.json') + ' · 共 ' + S.listen.items.length + ' 人';
  } catch (e) {
    var st2 = $('listenStatus');
    if (st2) st2.innerText = '读取失败：' + e;
  }
}

async function saveListenList() {
  var st = $('listenStatus');
  var mode = ($('listenMode') || {}).value || 'whitelist';
  var rows = Array.prototype.slice.call(document.querySelectorAll('#listenRows .listen-row'));
  var items = rows.map(function (r) {
    var n = r.querySelector('.lstNick');
    return { nickname: n ? n.value.trim() : '' };
  }).filter(function (x) { return x.nickname; });

  if (mode !== 'all_private' && !items.length) {
    alert('至少加一个人，或者把监听方式改成「所有私聊都回」');
    return;
  }
  if (st) st.innerText = '正在保存…';
  try {
    var d = await postJSON('/api/listen/save', { mode: mode, items: items });
    if (!d.ok) {
      alert('保存失败：' + (d.msg || '未知错误'));
      if (st) st.innerText = '保存失败';
      return;
    }
    var bad = d.listen_failed || [];
    toast(bad.length ? ('⚠️ 已保存，但 ' + bad.join('、') + ' 没听上') : (d.resubscribed ? '✅ 已保存并开始监听' : '✅ 已保存，点「启动」后开始'));
    await loadListen();
    loadBotStatus();
  } catch (e) {
    alert('保存失败：' + e);
    if (st) st.innerText = '保存失败：' + e;
  }
}

/* =============================================================================
   七、关系进度
   ============================================================================= */
function renderUsers(users) {
  var c = $('usersContainer');
  if (!c) return;
  var keys = Object.keys(users || {});
  if (!keys.length) {
    c.innerHTML = '<div class="empty-mini">还没有聊天记录。开始聊天后，每个人会出现在这里。</div>';
    return;
  }
  c.innerHTML = '';
  keys.forEach(function (uid) {
    var u = users[uid] || {};
    var aff = u.affection || 0;
    var chat = u.chat_count || 0;
    var s = u.force_stage ? stageInfo(null, u.force_stage) : stageByAffection(aff);

    var div = document.createElement('div');
    div.className = 'user-item';
    div.innerHTML =
      '<div class="user-top">' +
        '<span class="user-name">💬 ' + esc(uid) + '</span>' +
        '<span class="user-sub">已聊 <b>' + chat + '</b> 轮</span>' +
        '<span class="user-sub">好感 <b class="aff-text">' + aff + '</b> 分</span>' +
        '<span class="stage-pill ' + s.cls + '">' + s.text + '</span>' +
        '<span class="spacer"></span>' +
        '<select class="force-stage auto-width">' +
          '<option value="">按好感自动算</option>' +
          '<option value="1">🌱 锁定相识</option>' +
          '<option value="2">🍃 锁定相知</option>' +
          '<option value="3">❤️ 锁定相恋</option>' +
        '</select>' +
      '</div>' +
      '<div class="progress-bar-bg"><div class="progress-fill" style="width:' + Math.min(100, aff) + '%"></div></div>' +
      '<input type="range" class="aff-range" min="0" max="100" value="' + aff + '">';

    var range = div.querySelector('.aff-range');
    var fill = div.querySelector('.progress-fill');
    var affText = div.querySelector('.aff-text');
    range.oninput = function () {
      affText.innerText = this.value;
      fill.style.width = Math.min(100, this.value) + '%';
    };
    range.onchange = function () { saveAffection(uid, this.value); };

    var sel = div.querySelector('.force-stage');
    sel.value = u.force_stage || '';
    sel.onchange = function () { setForceStage(uid, this.value); };

    c.appendChild(div);
  });
}

async function saveAffection(uid, v) {
  try {
    await postJSON('/api/update_user', { user_id: uid, affection: parseInt(v, 10) });
    toast('已把 [' + uid + '] 的好感改成 ' + v + ' 分');
    await loadPersona();
    loadContacts();
  } catch (e) {
    console.error(e);
  }
}

async function setForceStage(uid, s) {
  try {
    await postJSON('/api/update_user', { user_id: uid, force_stage: s || null });
    toast('已更新 [' + uid + '] 的关系阶段');
    await loadPersona();
    loadContacts();
  } catch (e) {
    console.error(e);
  }
}

/* =============================================================================
   八、内心世界
   ============================================================================= */
async function loadMind() {
  if (!S.selectedUser) {
    ['mindMood', 'mindEnergy', 'mindWilling', 'mindFact', 'mindEpis'].forEach(function (k) { setText(k, '-'); });
    setText('mindEnergyBar', '-');
    var th0 = $('mindThoughts'), mm0 = $('mindMemory');
    if (th0) th0.innerText = '先在上面点一个好友，这里就会显示它的内心状态。';
    if (mm0) mm0.innerText = '还没有聊天对象。';
    return;
  }
  try {
    var d = await getJSON('/api/mind/state?user_id=' + encodeURIComponent(S.selectedUser));
    if (!d.ok) return;
    if (!d.snapshot) {
      var th = $('mindThoughts');
      if (th) th.innerText = d.msg || '还没有这个人的内心状态。';
      return;
    }
    renderMind(d.snapshot);
  } catch (e) {
    console.error('读取内心世界失败', e);
  }
}

function renderMind(s) {
  var emo = s.emotion || {}, rel = s.relationship || {}, st = s.state || {};
  var mem = s.memory || {}, per = s.personality || {};
  var counts = mem.counts || {};

  setText('mindMood', emo.label || emo.dominant);
  setText('mindEnergy', Math.round(st.energy || 0) + '/100');
  setText('mindEnergyBar', st.energy_text || '');
  setText('mindWilling', st.willingness_text || '');
  setText('mindFact', counts.facts || 0);
  setText('mindEpis', counts.episodes || 0);

  var rb = $('mindRelBar');
  if (rb) {
    rb.innerText = '亲密 ' + (rel.intimacy != null ? Math.round(rel.intimacy) : '-') +
      ' · 信任 ' + (rel.trust != null ? Math.round(rel.trust) : '-') +
      ' · 别扭 ' + (rel.tension != null ? Math.round(rel.tension) : '-') +
      ' · 阶段【' + (rel.stage_cn || '-') + '】· 已聊 ' + (rel.total_rounds || 0) + ' 轮';
  }
  var pa = $('mindPersona');
  if (pa) pa.innerText = per.text || per.summary || '还没漂移过，说的还是最初的人设';

  var th = $('mindThoughts');
  if (th) {
    var items = s.thoughts || [];
    th.innerHTML = items.length
      ? items.map(function (t) { return '<div class="log-ok">· ' + esc(t.text || t) + '</div>'; }).join('')
      : '<span class="log-empty">它还没有独自想过什么，聊几句就会有了。</span>';
  }

  var mm = $('mindMemory');
  if (mm) {
    var list = (mem.facts || []).concat(mem.episodes || []).concat(mem.summaries || []);
    mm.innerHTML = list.length
      ? list.map(function (it) {
          return '<div>· ' + esc(it.text || '') +
            ' <span style="color:#64748b">[' + esc(it.kind || 'fact') + ']</span> ' +
            '<a href="javascript:;" onclick="mindForgetOne(\'' + esc(it.id) + '\')" style="color:#f472b6">忘记</a></div>';
        }).join('')
      : '<span class="log-empty">它还没记住什么，多聊几句就会自己记下来。</span>';
  }

  var sch = st.schedule || {};
  if ($('mindQs') && document.activeElement !== $('mindQs')) $('mindQs').value = sch.quiet_start || '23:30';
  if ($('mindQe') && document.activeElement !== $('mindQe')) $('mindQe').value = sch.quiet_end || '07:30';
}

async function mindPost(url, payload) {
  if (!S.selectedUser) { toast('先选一个好友'); return null; }
  try {
    var body = Object.assign({ user_id: S.selectedUser }, payload || {});
    var d = await postJSON(url, body);
    setText('mindStatus', d.msg || '');
    if (!d.ok) toast(d.msg || '操作失败');
    return d;
  } catch (e) {
    toast('请求失败：' + e);
    return null;
  }
}

async function mindReflect() {
  var d = await mindPost('/api/mind/reflect');
  if (d && d.ok) { toast('💭 ' + d.msg); loadMind(); }
}

async function mindForgetOne(itemId) {
  if (!confirm('确定要让它忘掉这一条记忆吗？')) return;
  var d = await mindPost('/api/mind/forget', { item_id: itemId });
  if (d) { toast(d.msg); loadMind(); }
}

async function mindForgetAll() {
  if (!S.selectedUser) return;
  if (!confirm('这会彻底忘掉「' + S.selectedUser + '」的全部记忆和内心状态，确定吗？')) return;
  var d = await mindPost('/api/mind/forget', { all: true });
  if (d) { toast(d.msg); loadMind(); loadChatStream(true); }
}

async function saveMindSchedule() {
  var d = await mindPost('/api/mind/save_schedule', {
    quiet_start: (($('mindQs') || {}).value || '').trim(),
    quiet_end: (($('mindQe') || {}).value || '').trim()
  });
  if (d && d.ok) { toast('🕐 ' + (d.msg || '作息已保存')); loadMind(); }
}

/* =============================================================================
   九、操作记录
   ============================================================================= */
function renderLogs(logs) {
  var box = $('logBox');
  if (!box) return;
  if (!logs || !logs.length) {
    box.innerHTML = '<span class="log-empty">暂无操作记录。</span>';
    return;
  }
  box.innerHTML = logs.map(function (l) {
    return '<div class="' + (l.ok ? 'log-ok' : 'log-fail') + '">[' + esc(l.time) + '] ' +
      esc(l.action) + ' ➔ ' + esc(l.user_id) + '：' + esc(l.detail) + '</div>';
  }).join('');
}

/* =============================================================================
   十、抽屉
   ============================================================================= */
function openDrawer(name) {
  var mask = $('drawerMask');
  var target = name === 'brain' ? $('drawerBrain') : $('drawerPersona');
  if (!target) return;
  if (mask) mask.classList.add('show');
  target.classList.add('show');
  if (name === 'brain') loadLLM();
  if (name === 'persona') { loadPresets(); loadPersona(); }
}

function closeDrawer() {
  var mask = $('drawerMask');
  if (mask) mask.classList.remove('show');
  ['drawerBrain', 'drawerPersona'].forEach(function (id) {
    var el = $(id);
    if (el) el.classList.remove('show');
  });
}

/* =============================================================================
   十一、启动
   ============================================================================= */
function bindGlobal() {
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var panel = $('panelChat');
    if (panel && panel.classList.contains('expanded')) { toggleChatExpand(); return; }
    closeDrawer();
  });

  if ($('autoEnabled')) $('autoEnabled').onchange = function () { paintSwitches(); };
}

function startPolling() {
  clearInterval(S.statusTimer);
  clearInterval(S.chatTimer);
  clearInterval(S.contactsTimer);

  S.statusTimer = setInterval(loadBotStatus, 5000);
  S.contactsTimer = setInterval(function () {
    loadContacts();
    loadChatStream(false);
  }, 12000);
  S.chatTimer = setInterval(function () { loadChatStream(false); }, 4000);
}

async function boot() {
  bindGlobal();
  paintSwitches();

  await Promise.all([
    loadBotStatus(),
    loadLLM(),
    loadPresets(),
    loadPersona(),
    loadContacts(),
    loadListen(),
    loadAutoChat()
  ]);
  updateFirstRun();

  // 默认选中最近聊过的人，打开页面就能直接「跟随聊天」
  if (!S.selectedUser && S.contacts.length) {
    var pick = S.contacts[0].user_id;
    for (var i = 0; i < S.contacts.length; i++) {
      if (S.contacts[i].source === '监听中') { pick = S.contacts[i].user_id; break; }
    }
    selectContact(pick);
  } else {
    loadMind();
  }

  startPolling();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
