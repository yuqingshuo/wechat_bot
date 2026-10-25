/* ===== block 0 (from index.html inline <script>) ===== */
let globalData={}; let selectedUser=null; let contactsData=[]; let personaDirty=false; let mindData=null;
function showToast(msg){const t=document.getElementById('toast');t.innerText=msg;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2800)}
function escapeHtml(s){return String(s==null?'':s).replace(/[&<>"]/g,function(m){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]})}
function stagePillOf(stage){const map={'1':{text:'🌱 相识',cls:'pill-1'},'2':{text:'🍃 相知',cls:'pill-2'},'3':{text:'❤️ 相恋',cls:'pill-3'}};return map[stage]||map['1']}
function setText(id,v){const el=document.getElementById(id);if(el)el.innerText=(v==null||v==='')?'-':v}
async function loadMind(silent){if(!selectedUser){['mindMood','mindEnergy','mindWilling','mindFact','mindEpis'].forEach(function(k){setText(k,'-')});const th=document.getElementById('mindThoughts');const mm=document.getElementById('mindMemory');if(th)th.innerText='先在上面点一个聊天对象，这里就会显示它的内心状态。';if(mm)mm.innerText='还没有聊天对象。';return}try{const r=await fetch('/api/mind/state?user_id='+encodeURIComponent(selectedUser));const d=await r.json();if(!d.ok)return;if(!d.snapshot){const th=document.getElementById('mindThoughts');if(th)th.innerText=d.msg||'还没有这个人的内心状态。';return}mindData=d;renderMind(d.snapshot,d.user_id)}catch(e){if(!silent)console.error('读取内心世界失败',e)}}
function renderMind(s,uid){const emo=s.emotion||{},rel=s.relationship||{},st=s.state||{},mem=s.memory||{},per=s.personality||{};const counts=mem.counts||{};
setText('mindMood',emo.label||emo.dominant);
setText('mindEnergy',Math.round(st.energy||0)+'/100');
setText('mindEnergyBar',st.energy_text||'');
setText('mindWilling',st.willingness_text||'');
setText('mindFact',counts.facts||0);
setText('mindEpis',counts.episodes||0);
const rb=document.getElementById('mindRelBar');if(rb)rb.innerText='亲密 '+(rel.intimacy!=null?Math.round(rel.intimacy):'-')+' · 信任 '+(rel.trust!=null?Math.round(rel.trust):'-')+' · 别扭 '+(rel.tension!=null?Math.round(rel.tension):'-')+' · 阶段【'+(rel.stage_cn||'-')+'】· 已聊 '+(rel.total_rounds||0)+' 轮';
const pa=document.getElementById('mindPersona');if(pa)pa.innerText=(per.text||per.summary||'还没漂移过，说的还是最初的人设');
const th=document.getElementById('mindThoughts');if(th){const items=s.thoughts||[];th.innerHTML=items.length?items.map(function(t){return '<div class="log-ok">· '+escapeHtml(t.text||t)+'</div>'}).join(''):'<div style="color:#94a3b8">它还没有独自想过什么，聊几句就会有了。</div>'}
const mm=document.getElementById('mindMemory');const items=(mem.facts||[]).concat(mem.episodes||[]).concat(mem.summaries||[]);if(mm){mm.innerHTML=items.length?items.map(function(it){return '<div>· '+escapeHtml(it.text||'')+' <span style="color:#64748b">['+escapeHtml(it.kind||'fact')+']</span> <a href="javascript:;" onclick="mindForgetOne(\''+escapeHtml(it.id)+'\')" style="color:#f472b6">忘记</a></div>'}).join(''):'<div style="color:#94a3b8">它还没记住什么，多聊几句就会自己记下来。</div>'}
const qs=document.getElementById('mindQs'),qe=document.getElementById('mindQe'),sch=st.schedule||{};if(qs&&document.activeElement!==qs)qs.value=sch.quiet_start||'23:30';if(qe&&document.activeElement!==qe)qe.value=sch.quiet_end||'07:30'}
async function mindPost(url,payload){if(!selectedUser){showToast('先选中一个聊天对象');return null}try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign({user_id:selectedUser},payload||{}))});const d=await r.json();const st=document.getElementById('mindStatus');if(st)st.innerText=d.msg||'';if(!d.ok)showToast(d.msg||'操作失败');return d}catch(e){showToast('请求失败：'+e);return null}}
async function mindReflect(){const d=await mindPost('/api/mind/reflect');if(d&&d.ok){showToast('💭 '+d.msg);loadMind()}}
async function mindForgetOne(itemId){if(!confirm('确定要让它忘掉这一条记忆吗？'))return;const d=await mindPost('/api/mind/forget',{item_id:itemId});if(d)showToast(d.msg);loadMind()}
async function mindForgetAll(){if(!selectedUser)return;if(!confirm('这会彻底忘掉「'+selectedUser+'」的全部记忆和内心状态，确定吗？'))return;const d=await mindPost('/api/mind/forget',{all:true});if(d)showToast(d.msg);loadMind()}
async function saveMindSchedule(){const d=await mindPost('/api/mind/save_schedule',{quiet_start:(document.getElementById('mindQs').value||'').trim(),quiet_end:(document.getElementById('mindQe').value||'').trim()});if(d&&d.ok){showToast('🕐 '+(d.msg||'作息已保存'));loadMind()}}
async function loadData(){try{const r=await fetch('/api/get_persona');const d=await r.json();globalData=d;if(!personaDirty)fillPersonaFields(d);renderUsers(d.users);renderPromptView()}catch(e){console.error('加载配置失败',e)}}
const STAGE_META={'1':{icon:'🌱',title:'刚认识',range:'好感 0~29 分'},'2':{icon:'🍃',title:'熟了',range:'好感 30~79 分'},'3':{icon:'❤️',title:'亲密',range:'好感 80 分以上'}};
function renderPromptView(){const box=document.getElementById('promptView');if(!box)return;const d=globalData||{};const prof=d.bot_profile||{};const stages=d.stages||{};let html='<div class="pv-box"><div class="pv-name">📜 当前生效的提示词'+(prof.name?' · '+escapeHtml(prof.name):'')+'</div><div class="pv-desc">'+escapeHtml(prof.base_personality||'还没写性格')+'</div>';['1','2','3'].forEach(function(k){const s=stages[k]||{};const m=STAGE_META[k];html+='<div class="pv-name" style="margin-top:14px">'+m.icon+' '+m.title+'<span class="stage-threshold">'+m.range+'</span></div><div class="pv-desc">'+escapeHtml(s.description||'')+'</div><div class="pv-text">'+escapeHtml(s.prompt||'（空）')+'</div>';});box.innerHTML=html+'</div>'}
let presetsData=[];
function renderPresets(){const g=document.getElementById('presetGrid');if(!g)return;g.innerHTML='';presetsData.forEach(function(p){const c=document.createElement('div');c.className='preset-card'+(p.is_current?' on':'');const ident=((p.bot_profile||{}).identity||'').split('/')[0].trim();c.innerHTML='<div class="preset-emoji">'+p.emoji+'</div><div class="preset-nick">'+escapeHtml(p.nick)+'</div><div class="preset-tag">'+escapeHtml(p.tagline||'')+'</div><div class="preset-job">'+escapeHtml(ident)+'</div>'+(p.disclaimer?'<div class="preset-disc">'+escapeHtml(p.disclaimer)+'</div>':'')+(p.is_current?'<div class="preset-on">正在用</div>':'');c.title=(p.intro||'')+'\n\n'+((p.bot_profile||{}).base_personality||'')+'\n\n'+(p.disclaimer||'');c.onclick=function(){applyPreset(p)};g.appendChild(c)})}
async function loadPresets(){try{const r=await fetch('/api/persona_presets');const d=await r.json();if(!d.ok)return;presetsData=d.presets||[];renderPresets()}catch(e){console.error('读取人设列表失败',e)}}
async function applyPreset(p){if(!confirm('切换成「'+p.nick+'」？\n\n会覆盖现在的名字、身份、性格和三段提示词。\n（你自己改过的内容会被替换掉）\n\n提示：这套人设是虚构创作的人设，不对应任何真实个人。'))return;try{const r=await fetch('/api/apply_persona_preset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preset_id:p.id})});const d=await r.json();if(!d.ok){alert('切换失败：'+(d.msg||'未知错误'));return}personaDirty=false;showToast('✨ 已换成「'+d.nick+'」');await loadData();await loadPresets()}catch(e){alert('切换失败：'+e)}}
function fillPersonaFields(d){document.getElementById('botName').value=d.bot_profile.name||'';document.getElementById('botIdentity').value=d.bot_profile.identity||'';document.getElementById('botAge').value=d.bot_profile.age||'';document.getElementById('botGender').value=d.bot_profile.gender||'';document.getElementById('basePersonality').value=d.bot_profile.base_personality||'';document.getElementById('stageDesc1').value=d.stages['1'].description||'';document.getElementById('stagePrompt1').value=d.stages['1'].prompt||'';document.getElementById('stageDesc2').value=d.stages['2'].description||'';document.getElementById('stagePrompt2').value=d.stages['2'].prompt||'';document.getElementById('stageDesc3').value=d.stages['3'].description||'';document.getElementById('stagePrompt3').value=d.stages['3'].prompt||''}
function markPersonaDirty(){personaDirty=true}

/* ===== block 1 (from index.html inline <script>) ===== */
async function loadContacts(){try{const r=await fetch('/api/get_contacts');const d=await r.json();if(!d.ok)return;contactsData=d.contacts||[];const st=document.getElementById('wxStatus');if(d.wx_online){st.className='wx-status online';st.innerText='● 微信已连上'+(d.wx_nickname?'（当前登录：'+d.wx_nickname+'）':'')+'，点下面卡片就能聊天啦。'}else{st.className='wx-status offline';st.innerText='⚠ 微信还没连上：先点最上面的绿色「启动机器人」按钮，连上后这里会自动变绿。'}renderContacts(contactsData);renderLogs(d.logs||[])}catch(e){console.error('加载好友列表失败',e)}}
function renderContacts(contacts){const grid=document.getElementById('contactGrid');const kwEl=document.getElementById('contactSearch');const kw=(kwEl&&kwEl.value?kwEl.value:'').trim().toLowerCase();const list=kw?(contacts||[]).filter(function(c){return String(c.user_id||'').toLowerCase().indexOf(kw)>=0}):(contacts||[]);grid.innerHTML='';if(!list.length){grid.innerHTML=kw?'<div style="padding:16px;color:var(--muted);font-size:14px">没有找到「'+escapeHtml(kw)+'」，换个关键字试试。</div>':'<div style="padding:16px;color:var(--muted);font-size:14px">还没读到好友：先启动机器人并连上微信，这里会自动出现好友卡片。</div>';return}
list.forEach(function(c){const s=stagePillOf(c.stage);const isAuto=autoTargets.indexOf(c.user_id)>=0;const div=document.createElement('div');div.className='contact-chip'+(selectedUser===c.user_id?' active':'');div.onclick=function(){selectContact(c.user_id)};div.innerHTML='<div class="c-name">💬 '+escapeHtml(c.user_id)+'</div><div class="c-meta"><span class="stage-pill '+s.cls+'">'+s.text+'</span><span>❤ '+(c.affection||0)+'</span></div>';const row=div.querySelector('.c-meta');const b=document.createElement('span');b.className='c-auto'+(isAuto?' on':'');b.innerText=isAuto?'🤖 会主动聊':'🤖 不主动';b.title='点一下切换：要不要主动找 TA 聊天';b.onclick=function(ev){ev.stopPropagation();toggleAutoTarget(c.user_id,!isAuto)};row.appendChild(b);grid.appendChild(div)})}
function selectContact(userId){selectedUser=userId;const c=contactsData.find(function(x){return x.user_id===userId})||{user_id:userId,affection:0,stage:'1',chat_count:0,source:'手动选择'};const s=stagePillOf(c.stage);document.getElementById('targetName').innerText=c.user_id;const pill=document.getElementById('targetStage');pill.className='stage-pill '+s.cls;pill.innerText=s.text;document.getElementById('targetMeta').innerText='好感 '+(c.affection||0)+' 分 · 已聊 '+(c.chat_count||0)+' 轮';document.getElementById('btnSend').disabled=false;document.getElementById('btnGen').disabled=false;document.getElementById('btnGenSend').disabled=false;renderContacts(contactsData);showToast('已选中 '+c.user_id+'，在下面输入框写话就能发');checkListenWarn();loadMind();refreshAutoChatBtn()}
async function sendSelectedMessage(){if(!selectedUser){showToast('先点上面任意一张好友卡片，选中要聊的人');return}const message=document.getElementById('messageInput').value.trim();if(!message){showToast('先在输入框里写一句话');return}const btn=document.getElementById('btnSend');btn.disabled=true;btn.innerText='发送中…';try{const r=await fetch('/api/send_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:selectedUser,message:message,humanlike:document.getElementById('humanlikeChk').checked,count_affection:document.getElementById('affectionChk').checked})});const res=await r.json();if(res.ok){showToast('✅ 已发送');document.getElementById('messageInput').value=''}else{alert('发送失败：'+(res.msg||'未知错误'))}setTimeout(loadContacts,900)}catch(e){alert('发送请求失败：'+e)}finally{btn.disabled=false;btn.innerText='🚀 发送'}}
async function aiOutreach(doSend){if(!selectedUser){showToast('先点上面任意一张好友卡片，选中要聊的人');return}
if(listenModeNow!=='all_private'&&!listenItems.some(function(x){return x.nickname===selectedUser})){showToast('⚠️ TA 还没进监听名单，发出去它也不会回你 —— 点上方黄色提示一键加入');}const btn=document.getElementById(doSend?'btnGenSend':'btnGen');const old=btn.innerText;btn.disabled=true;btn.innerText='AI 正在想…';try{const r=await fetch('/api/ai_outreach',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:selectedUser,topic:document.getElementById('topicInput').value.trim(),send:doSend,count_affection:document.getElementById('affectionChk').checked})});const res=await r.json();if(!res.ok){alert('生成失败：'+(res.msg||'未知错误'));return}document.getElementById('messageInput').value=res.message;showToast(res.sent?'💌 已经发出去了':'✍️ 写好了，看看满意不，满意就点「发送」');setTimeout(loadContacts,1000)}catch(e){alert('请求失败：'+e)}finally{btn.disabled=false;btn.innerText=old}}

/* ===== block 2 (from index.html inline <script>) ===== */
let runtimeSaving=false;
const BOT_STATE_UI={'stopped':['off','⚪ 没在工作'],'connecting':['connecting','🟡 正在连接…'],'running':['on','🟢 自动工作中'],'stopping':['connecting','🟡 正在停止…'],'error':['err','🔴 出问题了']};
async function loadBotStatus(){try{const r=await fetch('/api/bot/status');const d=await r.json();if(!d.ok)return;const info=BOT_STATE_UI[d.state]||['off',d.state_text||d.state||'未知'];const pill=document.getElementById('botStatePill');pill.className='bot-pill '+info[0];pill.innerText=info[1];const busy=(d.state==='connecting'||d.state==='stopping');document.getElementById('btnBotStart').disabled=!!d.running||busy;document.getElementById('btnBotStop').disabled=!d.running&&!busy;document.getElementById('btnEasyMode').disabled=!!d.running||busy;
document.getElementById('stMsg').innerText=d.messages_received||0;document.getElementById('stReply').innerText=d.replies_sent||0;document.getElementById('stMem').innerText=d.memory_rounds||0;document.getElementById('stQueue').innerText=d.queue_pending||0;
let html='微信：<b>'+(d.wx_online?'已连上'+(d.wx_nickname?'（'+escapeHtml(d.wx_nickname)+'）':''):'还没连上')+'</b> ｜ 已工作：<b>'+escapeHtml(d.uptime_text||'—')+'</b>';
html+='<br>在听谁说话：<b>'+(d.listen_mode==='whitelist'?'只听 '+escapeHtml((d.whitelist||[]).join('、')||'（还没选人）'):'所有私聊好友')+'</b>（'+((d.listen_targets||[]).length)+' 个会话）';
if((d.listen_failed||[]).length){html+='<br>⚠ 这几个人没听上：'+escapeHtml((d.listen_failed||[]).join('、'))}
const pv=d.active_provider||{};html+='<br>用的大脑：<b>'+escapeHtml(pv.name||pv.id||'—')+'</b> ｜ 存了 <b>'+(d.memory_friends||0)+'</b> 位好友、<b>'+(d.memory_messages||0)+'</b> 句话';
if(d.last_message_at){html+='<br>最近一句：<b>'+escapeHtml(d.last_message_from||'')+'</b> 说 '+escapeHtml(d.last_message_text||'')}
if(d.last_reply_text){html+='<br>最新回复：'+escapeHtml(d.last_reply_text)}
if(d.state==='error'&&d.last_error){html+='<br>❗ '+escapeHtml(d.last_error)}
document.getElementById('botStatus').innerHTML=html;
const hs=document.getElementById('heroState');if(hs){const wl=(d.whitelist||[]).join('、');const bad=d.listen_failed||[];let t=(d.running?'✅ 正在工作':'⭕️ 没在工作')+' ｜ '+(d.wx_online?'微信已连上':'微信还没连上')+' ｜ '+(wl?('只听：'+wl):(d.listen_mode==='whitelist'?'白名单为空':'所有私聊'))+' ｜ 收到 '+(d.messages_received||0)+' 条';if(bad.length){t+=' ｜ ⚠️ 没听上：'+bad.join('、')+'（昵称对不上，去 config.py 的 LISTEN_LIST 改成通讯录里的原样）'}hs.innerText=t}
if(!runtimeSaving){const rt=d.runtime||{};document.getElementById('rtAutoStart').checked=rt.auto_start===true;document.getElementById('rtAutoReply').checked=rt.auto_reply!==false;document.getElementById('rtAutoMemory').checked=rt.auto_save_memory!==false;document.getElementById('rtAutoReconnect').checked=rt.auto_reconnect!==false;document.getElementById('rtRetry').value=rt.connect_retry||3;paintSwitches()}}catch(e){console.error('读取运行状态失败',e)}}
function paintSwitches(){[['rtAutoStart','swAutoStart'],['rtAutoReply','swAutoReply'],['rtAutoMemory','swAutoMemory'],['rtAutoReconnect','swAutoReconnect'],['autoEnabled','swAutoChat']].forEach(function(p){const box=document.getElementById(p[0]);const card=document.getElementById(p[1]);if(box&&card){card.classList.toggle('on',!!box.checked)}})}
async function startBot(){document.getElementById('btnBotStart').disabled=true;const pill=document.getElementById('botStatePill');pill.className='bot-pill connecting';pill.innerText='🟡 正在连接…';try{const r=await fetch('/api/bot/start',{method:'POST'});const d=await r.json();showToast(d.msg||'收到！正在自动连微信，稍等十几秒…')}catch(e){alert('启动失败：'+e)}loadBotStatus()}
async function stopBot(){document.getElementById('btnBotStop').disabled=true;try{const r=await fetch('/api/bot/stop',{method:'POST'});const d=await r.json();showToast(d.msg||'已停下，不会自动回复了')}catch(e){alert('停止失败：'+e)}loadBotStatus();loadAutoChat()}
async function saveRuntime(showTip){runtimeSaving=true;paintSwitches();const payload={auto_start:document.getElementById('rtAutoStart').checked,auto_reply:document.getElementById('rtAutoReply').checked,auto_save_memory:document.getElementById('rtAutoMemory').checked,auto_reconnect:document.getElementById('rtAutoReconnect').checked,connect_retry:parseInt(document.getElementById('rtRetry').value,10)||3};try{const r=await fetch('/api/bot/save_runtime',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(d.ok){if(showTip!==false)showToast('✅ 已保存，重启也不这')}else{alert('保存失败：'+(d.msg||'未知错误'))}}catch(e){alert('保存失败：'+e)}runtimeSaving=false;loadBotStatus()}

/* ===== 傻瓜模式：人设 + API 弄好后，点一下全自动启动，其他不用管 ===== */
async function easyMode(){
  const btn=document.getElementById('btnEasyMode');
  btn.disabled=true;btn.innerText='检查中…';
  try{
    let st=null;
    try{const r=await fetch('/api/bot/status');st=await r.json();}catch(e){}
    if(st&&st.running){showToast('✅ 已经在自动工作中了，不用重复启动');loadBotStatus();return}

    let persona=null;
    try{const r=await fetch('/api/persona_presets');persona=await r.json();}catch(e){}
    const hasPersona=persona&&persona.current_name;

    let prov=null;
    try{const r=await fetch('/api/llm/providers');prov=await r.json();}catch(e){}
    const activeId=prov&&prov.active_provider;
    const hasAPI=!!activeId;

    const missing=[];
    if(!hasPersona)missing.push('人设（去「改成你想要的」保存一下名字/性格，或套用一个预设人设）');
    if(!hasAPI)missing.push('AI 大脑（去「更多设置 → AI 大脑」配置并激活一个模型）');

    if(missing.length){
      btn.disabled=false;btn.innerText='🤖 傻瓜模式';
      alert('还没准备好，请先完成：\n• '+missing.join('\n• ')+'\n\n弄好后再点「傻瓜模式」，它就会全自动启动。');
      return;
    }

    // 傻瓜模式：只负责「当前这次」启动，不动 auto_start（不写死成 true，否则程序重启后会自动自己跑起来）
    // 保留用户自己在「运行时配置」里的开机自启选择；本次启动通过 /api/bot/start 触发
    try{const r=await fetch('/api/bot/save_runtime',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({auto_reply:true,auto_save_memory:true,auto_reconnect:true,connect_retry:3})});const d=await r.json();if(!d.ok){throw new Error(d.msg||'保存运行配置失败')}}catch(e){btn.disabled=false;btn.innerText='🤖 傻瓜模式';alert('保存运行设置失败：'+e);return}

    try{const r=await fetch('/api/bot/start',{method:'POST'});const d=await r.json();if(d.ok){showToast('🚀 傻瓜模式已启动：自动连微信、自动回消息、自动存档，其他什么都不用管了');}else{throw new Error(d.msg||'启动失败')}}catch(e){btn.disabled=false;btn.innerText='🤖 傻瓜模式';alert('启动失败：'+e);return}

    btn.disabled=false;btn.innerText='🤖 傻瓜模式';
    loadBotStatus();
  }catch(e){
    btn.disabled=false;btn.innerText='🤖 傻瓜模式';
    alert('傻瓜模式出错：'+e);
  }
}


/* ===== block 3 (from index.html inline <script>) ===== */
let autoTargets=[]; let autoDirty=false; let autoChatCfg=null;
function refreshAutoChatBtn(){const btn=document.getElementById('btnAutoChat');if(!btn)return;if(!selectedUser){btn.disabled=true;btn.classList.remove('on');btn.innerText='🤖 自动聊天';btn.title='先点一张好友卡片选中人，再点这里';return}const on=!!(autoChatCfg&&autoChatCfg.enabled&&(autoChatCfg.targets||[]).indexOf(selectedUser)>=0);btn.disabled=false;btn.classList.toggle('on',on);btn.innerText=on?'⏹ 停止自动聊天':'🤖 自动聊天';btn.title=on?('正在自动陪聊 '+selectedUser+'，点一下停止'):('点一下，让 AI 持续主动陪 '+selectedUser+' 聊天')}
async function toggleAutoChatWith(){if(!selectedUser){showToast('先点上面任意一张好友卡片，选中要聊的人');return}
const btn=document.getElementById('btnAutoChat');btn.disabled=true;btn.innerText='设置中…';
try{
  let st=null;try{const r=await fetch('/api/bot/status');st=await r.json()}catch(e){}
  if(!st||!st.running||!st.wx_online){alert('机器人还没连上微信：先点右上角「🤖 傻瓜模式」把机器人启动起来，等微信连上后再回来点「自动聊天」。');return}
  const on=!!(autoChatCfg&&autoChatCfg.enabled&&(autoChatCfg.targets||[]).indexOf(selectedUser)>=0);
  if(on){
    const r=await fetch('/api/save_auto_chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:false})});const d=await r.json();
    if(!d.ok){alert('停止失败：'+(d.msg||'未知原因'));return}
    if(autoChatCfg)autoChatCfg.enabled=false;
    showToast('⏹ 已停止自动聊天，它不会再主动找 '+selectedUser+' 说话了');
  }else{
    // 关键：白名单模式下必须把 TA 也加进监听名单，否则 TA 回你时 on_message 会按白名单静默拦截，机器人就装聋不理
    if(listenModeNow!=='all_private'&&!listenItems.some(function(x){return x.nickname===selectedUser})){
      const items=listenItems.slice();items.push({nickname:selectedUser});
      try{const r=await fetch('/api/listen/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:listenModeNow,items:items})});const d=await r.json();if(d.ok){listenItems=d.items||items;listenModeNow=d.mode||listenModeNow;showToast('✅ 已把 '+selectedUser+' 加入监听名单，TA 回你会自动回')}}catch(e){console.error('加入监听名单失败',e)}
    }
    const payload={enabled:true,targets:[selectedUser],interval_minutes:2,min_gap_hours:0,max_per_day:100,active_start:0,active_end:24,use_context:true,reply_pending_first:true,jitter:true,count_affection:true};
    const r=await fetch('/api/save_auto_chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();
    if(!d.ok){alert('开启失败：'+(d.msg||'未知原因'));return}
    autoChatCfg=Object.assign({},autoChatCfg||{},payload);
    showToast('🤖 已开启：它会持续主动陪 '+selectedUser+' 聊天（每 2 分钟内找话题或接话，TA 回了就自动回）');
    try{await fetch('/api/auto_chat_now',{method:'POST'})}catch(e){}
  }
  loadAutoChat();loadContacts();
}catch(e){alert('自动聊天设置失败：'+e)}
finally{refreshAutoChatBtn()}}
async function loadAutoChat(){try{const r=await fetch('/api/get_auto_chat');const d=await r.json();if(!d.ok)return;const cfg=d.config||{};const st=d.status||{};autoTargets=st.targets||[];autoChatCfg=cfg;
if(!autoDirty){document.getElementById('autoEnabled').checked=!!cfg.enabled;document.getElementById('autoInterval').value=cfg.interval_minutes||60;document.getElementById('autoStart').value=(cfg.active_start==null?9:cfg.active_start);document.getElementById('autoEnd').value=(cfg.active_end==null?23:cfg.active_end);document.getElementById('autoMax').value=cfg.max_per_day||20;document.getElementById('autoJitter').checked=cfg.jitter!==false;document.getElementById('autoAffection').checked=cfg.count_affection!==false;document.getElementById('autoTopics').value=cfg.topics||'';paintSwitches()}
const box=document.getElementById('autoStatus');box.className='auto-status'+(st.enabled?' on':'');
let html=(st.enabled?'🟢 主动聊天开着':'⚪ 主动聊天关着')+' ｜ 今天已主动说了 <b>'+(st.count_today||0)+'</b> / '+(st.max_per_day||0)+' 句';
html+='<br>现在：'+escapeHtml(st.reason||'');
if(st.last_run_text){html+='<br>上次：'+escapeHtml(st.last_run_text)+' ➔ '+escapeHtml(st.last_target||'-')}
if(st.next_run_text){html+=' ｜ 下次大概：'+escapeHtml(st.next_run_text)}
if(!st.wx_online){html+='<br>⚠ 微信还没连上，连上后会自动继续。'}
box.innerHTML=html;renderAutoTargetChips();refreshAutoChatBtn()}catch(e){console.error('加载主动聊天失败',e)}}
function renderAutoTargetChips(){const box=document.getElementById('autoTargetChips');if(!box)return;const names=(contactsData||[]).map(function(c){return c.user_id});autoTargets.forEach(function(t){if(names.indexOf(t)<0)names.push(t)});box.innerHTML='';if(!names.length){box.innerHTML='<span style="font-size:13px;color:var(--muted)">好友列表还没读到，连上微信后在这里点人名就行。</span>';return}names.forEach(function(n){const on=autoTargets.indexOf(n)>=0;const chip=document.createElement('span');chip.className='t-chip'+(on?' on':'');chip.innerText=(on?'✅ ':'○ ')+n;chip.onclick=function(){toggleAutoTarget(n,!on)};box.appendChild(chip)})}
async function postAutoChat(payload,okText){try{const r=await fetch('/api/save_auto_chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const res=await r.json();if(res.ok){if(res.status&&res.status.targets)autoTargets=res.status.targets;showToast('✅ '+okText)}else{alert('保存失败：'+(res.msg||'未知错误'))}renderAutoTargetChips();renderContacts(contactsData);loadAutoChat()}catch(e){alert('请求失败：'+e)}}
function toggleAutoTarget(name,on){const next=autoTargets.slice();const i=next.indexOf(name);if(on&&i<0)next.push(name);if(!on&&i>=0)next.splice(i,1);autoTargets=next;renderAutoTargetChips();renderContacts(contactsData);postAutoChat({targets:next},'主动聊天名单已更新')}
function collectAutoForm(){return{enabled:document.getElementById('autoEnabled').checked,interval_minutes:parseInt(document.getElementById('autoInterval').value||'60',10),active_start:parseInt(document.getElementById('autoStart').value||'9',10),active_end:parseInt(document.getElementById('autoEnd').value||'23',10),max_per_day:parseInt(document.getElementById('autoMax').value||'20',10),jitter:document.getElementById('autoJitter').checked,count_affection:document.getElementById('autoAffection').checked,topics:document.getElementById('autoTopics').value,targets:autoTargets}}
async function saveAutoChat(){const f=collectAutoForm();autoDirty=false;await postAutoChat(f,f.enabled?('已打开：每 '+f.interval_minutes+' 分钟主动找人说一句'):'已保存（目前是关闭状态）')}
async function onAutoEnabledChange(){const on=document.getElementById('autoEnabled').checked;autoDirty=false;paintSwitches();await postAutoChat({enabled:on,targets:autoTargets},on?'已打开，时间一到它自己就会去说话':'已关闭，它不会再主动开口')}
async function autoChatNow(){const btn=document.getElementById('btnAutoNow');const old=btn.innerText;btn.disabled=true;btn.innerText='正在说…';try{const r=await fetch('/api/auto_chat_now',{method:'POST'});const res=await r.json();showToast(res.ok?('▶️ '+res.msg):('没说成：'+(res.msg||'未知原因')));setTimeout(function(){loadContacts();loadAutoChat()},3000)}catch(e){alert('请求失败：'+e)}finally{btn.disabled=false;btn.innerText=old}}

/* ===== block 4 (from index.html inline <script>) ===== */
function renderLogs(logs){const box=document.getElementById('logBox');if(!logs||!logs.length){box.innerHTML='暂无操作记录。';return}box.innerHTML=logs.map(function(l){return '<div class="'+(l.ok?'log-ok':'log-fail')+'">['+l.time+'] '+escapeHtml(l.action)+' ➔ '+escapeHtml(l.user_id)+'：'+escapeHtml(l.detail)+'</div>'}).join('')}
function getStageInfo(u){if(u.force_stage){const m={'1':'🌱 相识（你指定的）','2':'🍃 相知（你指定的）','3':'❤️ 相恋（你指定的）'};return{text:m[u.force_stage],cls:'pill-'+u.force_stage}}const a=u.affection||0;if(a<30)return{text:'🌱 相识',cls:'pill-1'};if(a<80)return{text:'🍃 相知',cls:'pill-2'};return{text:'❤️ 相恋',cls:'pill-3'}}
function onAffSliderChange(uid,v){document.getElementById('affText-'+uid).innerText=v;document.getElementById('progressFill-'+uid).style.width=Math.min(100,v)+'%'}
async function saveAffection(uid,v){try{await fetch('/api/update_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,affection:parseInt(v)})});showToast('已把 ['+uid+'] 的好感改成 '+v+' 分');loadData()}catch(e){console.error(e)}}
async function setForceStage(uid,s){try{await fetch('/api/update_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,force_stage:s||null})});showToast('已更新 ['+uid+'] 的关系');loadData()}catch(e){console.error(e)}}
async function saveAllSettings(){const payload={bot_profile:{name:document.getElementById('botName').value.trim(),identity:document.getElementById('botIdentity').value.trim(),age:document.getElementById('botAge').value.trim(),gender:document.getElementById('botGender').value.trim(),base_personality:document.getElementById('basePersonality').value.trim()},stages:{'1':{description:document.getElementById('stageDesc1').value.trim(),prompt:document.getElementById('stagePrompt1').value.trim()},'2':{description:document.getElementById('stageDesc2').value.trim(),prompt:document.getElementById('stagePrompt2').value.trim()},'3':{description:document.getElementById('stageDesc3').value.trim(),prompt:document.getElementById('stagePrompt3').value.trim()}}};try{const r=await fetch('/api/save_persona',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const res=await r.json();if(res.ok){personaDirty=false;showToast('✨ 人设已保存，立刻生效！');await loadData();await loadPresets()}else{alert('保存失败：'+(res.msg||'未知错误'))}}catch(e){alert('保存请求失败：'+e)}}

/* ===== block 5 (from index.html inline <script>) ===== */
function renderUsers(users){const c=document.getElementById('usersContainer');c.innerHTML='';if(!users||!Object.keys(users).length){c.innerHTML='<div style="color:var(--muted);font-size:14px;text-align:center;padding:20px">还没有聊天记录，开始聊天后每个人会出现在这里。</div>';return}
for(const uid of Object.keys(users)){const u=users[uid];const aff=u.affection||0;const chat=u.chat_count||0;const s=getStageInfo(u);const div=document.createElement('div');div.className='user-item';
div.innerHTML='<div class="user-meta"><span class="user-name">💬 '+escapeHtml(uid)+'</span><div class="user-stats"><span>已聊 <b>'+chat+'</b> 轮</span><span>好感 <b id="affText-'+escapeHtml(uid)+'">'+aff+'</b> 分</span><span class="stage-pill '+s.cls+'">'+s.text+'</span></div></div><div class="progress-bar-bg"><div class="progress-bar-fill" id="progressFill-'+escapeHtml(uid)+'" style="width:'+Math.min(100,aff)+'%"></div></div><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-top:4px"><div style="flex:1;min-width:240px" class="slider-control"><span style="font-size:12px;color:var(--muted)">拖动改好感：</span><input type="range" min="0" max="100" value="'+aff+'"></div><div style="display:flex;align-items:center;gap:8px"><span style="font-size:12px;color:var(--muted)">直接定关系：</span><select style="width:auto;padding:6px 10px;font-size:13px"><option value="">按好感自动算</option><option value="1">🌱 锁定相识</option><option value="2">🍃 锁定相知</option><option value="3">❤️ 锁定相恋</option></select></div></div>';
(function(id,force){const slider=div.querySelector('input[type="range"]');slider.oninput=function(){onAffSliderChange(id,this.value)};slider.onchange=function(){saveAffection(id,this.value)};const sel=div.querySelector('select');sel.value=force||'';sel.onchange=function(){setForceStage(id,this.value)}})(uid,u.force_stage);
c.appendChild(div)}}
let llmProviders=[];
let listenItems=[];let listenModeNow='whitelist';
function checkListenWarn(){
const w=document.getElementById('listenWarn');if(!w)return;
if(!selectedUser){w.style.display='none';return}
const on=listenItems.some(function(x){return x.nickname===selectedUser});
if(listenModeNow==='all_private'){w.style.display='none';return}
if(on){w.style.display='none';return}
w.style.display='block';w.className='tip';
w.style.color='#b45309';w.style.background='#fef3c7';w.style.border='1px solid #fcd34d';
w.innerHTML='⚠️ <b>'+escapeHtml(selectedUser)+'</b> 还不在监听名单里 —— 现在它发的消息你收不到，也不会自动回。'
+'<button class="btn-primary" style="margin-left:10px" onclick="addCurrentToListen()">➕ 把 TA 加入监听名单</button>';}
async function addCurrentToListen(){
if(!selectedUser)return;
const items=listenItems.slice();
if(!items.some(function(x){return x.nickname===selectedUser})){items.push({nickname:selectedUser})}
try{const r=await fetch('/api/listen/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:listenModeNow,items:items})});
const d=await r.json();if(!d.ok){alert('加入失败：'+(d.msg||''));return}
listenItems=d.items||items;listenModeNow=d.mode||listenModeNow;
const bad=d.listen_failed||[];
showToast(bad.indexOf(selectedUser)>=0?('⚠️ 已加入，但没听上：昵称对不上，请核对'):'✅ 已加入监听，TA 回你消息会自动回');
checkListenWarn();loadBotStatus();}catch(e){alert('加入失败：'+e)}}
function addListenRow(nick,failed){
const box=document.getElementById('listenRows');if(!box)return;
const row=document.createElement('div');row.className='grid-2';row.style.marginBottom='8px';row.dataset.failed=failed?'1':'';
row.innerHTML='<div><label>微信昵称 / 备注 <small>· 和通讯录里一模一样</small></label><input type="text" class="lstNick" value="'+escapeHtml(nick||'')+'" placeholder="例如：我的大号"></div>';
const del=document.createElement('button');del.className='btn-ghost';del.style.alignSelf='end';del.innerText='🗑️ 删除';del.onclick=function(){row.remove()};
row.appendChild(del);
if(failed){const w=document.createElement('div');w.className='tip';w.style.gridColumn='1/-1';w.style.color='var(--danger,#e5484d)';w.innerText='❌ 上次没听上：微信通讯录里没找到这个名字，请核对后重试';row.appendChild(w)}
box.appendChild(row)}

async function loadListenList(){
try{const r=await fetch('/api/listen/list');const d=await r.json();if(!d.ok)return;
const box=document.getElementById('listenRows');if(box)box.innerHTML='';
const md=document.getElementById('listenMode');if(md)md.value=d.mode||'whitelist';
listenModeNow=d.mode||'whitelist';listenItems=d.items||[];
const failed=d.listen_failed||[];
(d.items||[]).forEach(function(it){addListenRow(it.nickname,failed.indexOf(it.nickname)>=0)});
if(!(d.items||[]).length)addListenRow('',false);
const st=document.getElementById('listenStatus');if(st)st.innerText=(d.store_file||'listen_list.json')+' · 共 '+(d.items||[]).length+' 人';
checkListenWarn();
}catch(e){const st=document.getElementById('listenStatus');if(st)st.innerText='读取失败：'+e}}

async function saveListenList(){
const st=document.getElementById('listenStatus');
const rows=Array.from(document.querySelectorAll('#listenRows .grid-2'));
const items=rows.map(function(r){const n=r.querySelector('.lstNick');return{nickname:n?n.value.trim():''}}).filter(function(x){return x.nickname});
if(document.getElementById('listenMode').value!=='all_private'&&!items.length){alert('至少加一个人，或者把监听方式改成「所有私聊都回」');return}
if(st)st.innerText='正在保存…';
try{const r=await fetch('/api/listen/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:document.getElementById('listenMode').value,items:items})});
const d=await r.json();
if(!d.ok){alert('保存失败：'+(d.msg||'未知错误'));if(st)st.innerText='保存失败';return}
const bad=d.listen_failed||[];
showToast(bad.length?('⚠️ 已保存，但 '+bad.join('、')+' 没听上'):(d.resubscribed?'✅ 已保存并开始监听':'✅ 已保存，点「启动」后开始'));
await loadListenList();checkListenWarn();loadBotStatus();
}catch(e){alert('保存失败：'+e);if(st)st.innerText='保存失败：'+e}}

async function loadLLM(){const st=document.getElementById('llmStatus');try{const r=await fetch('/api/llm/providers');const d=await r.json();if(!d.ok){if(st)st.innerText='读不到大脑列表';return}llmProviders=d.providers||[];const sel=document.getElementById('llmSelect');sel.innerHTML='';llmProviders.forEach(function(p){const o=document.createElement('option');const pid=p.id||p.provider_id||'';o.value=pid;o.innerText=(p.name||pid)+'（'+(p.model||'未设模型')+'）';if(pid===d.active_provider)o.selected=true;sel.appendChild(o)});fillLLMForm(d.active_provider);if(st&&sel.options[sel.selectedIndex])st.innerText='当前大脑：'+sel.options[sel.selectedIndex].text}catch(e){if(st)st.innerText='读取失败：'+e}}
function fillLLMForm(activeId){let p=null;for(const x of llmProviders){if((x.id||x.provider_id)===activeId){p=x;break}}p=p||llmProviders[0]||{};document.getElementById('llmName').value=p.name||'';document.getElementById('llmBaseUrl').value=p.base_url||'';document.getElementById('llmModel').value=p.model||'';document.getElementById('llmTemp').value=(p.temperature==null?'':p.temperature);const ak=document.getElementById('llmApiKey');ak.value='';const src=p.api_key_source||(p.has_api_key?'saved':'none');ak.dataset.hasKey=p.has_api_key?'1':'';ak.dataset.src=src;const SRC_TXT={env:'已配置（来自环境变量，留空不修改）',config_local:'已配置（来自 config_local.py，留空不修改）',saved:'已配置（留空表示不修改）',none:'sk-…'};ak.placeholder=SRC_TXT[src]||SRC_TXT.saved;const hint=document.getElementById('llmKeyHint');if(hint){if(src==='env'||src==='config_local'){hint.innerText='🔒 当前密钥来自'+(src==='env'?'环境变量':'config_local.py')+'，优先级高于这里的输入框，填了也不会生效';hint.style.display=''}else if(src==='saved'){hint.innerText='🔒 密钥已存在服务端，不会显示在页面上；留空即保持不变';hint.style.display=''}else{hint.innerText='';hint.style.display='none'}}}
async function switchLLM(){const sel=document.getElementById('llmSelect');const id=sel.value;if(!id)return;try{const r=await fetch('/api/llm/switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider_id:id})});const d=await r.json();if(d.ok){showToast('🧠 已换大脑，立刻生效');fillLLMForm(id)}else{alert('切换失败：'+(d.msg||'未知错误'))}loadBotStatus()}catch(e){alert('切换失败：'+e)}}
async function saveLLM(){const sel=document.getElementById('llmSelect');const id=sel.value;if(!id){showToast('列表还没读出来，稍等两秒再点');return}const t=document.getElementById('llmTemp').value.trim();const payload={id:id,name:document.getElementById('llmName').value.trim(),base_url:document.getElementById('llmBaseUrl').value.trim(),api_key:document.getElementById('llmApiKey').value.trim(),model:document.getElementById('llmModel').value.trim()};if(t!=='')payload.temperature=parseFloat(t);try{const r=await fetch('/api/llm/save_provider',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(d.ok){showToast('✅ 大脑设置已保存，立刻生效');loadLLM()}else{alert('保存失败：'+(d.msg||'未知错误'))}}catch(e){alert('保存失败：'+e)}}
['botName','botIdentity','botAge','botGender','basePersonality','stageDesc1','stagePrompt1','stageDesc2','stagePrompt2','stageDesc3','stagePrompt3'].forEach(function(id){const el=document.getElementById(id);if(el)el.addEventListener('input',markPersonaDirty)});
['autoInterval','autoStart','autoEnd','autoMax','autoTopics'].forEach(function(id){const el=document.getElementById(id);if(el)el.addEventListener('input',function(){autoDirty=true})});
['autoJitter','autoAffection'].forEach(function(id){const el=document.getElementById(id);if(el)el.addEventListener('change',function(){autoDirty=true})});
loadData();loadPresets();loadContacts();loadAutoChat();loadBotStatus();loadLLM();loadMind();loadListenList();
setInterval(function(){loadData();loadContacts();loadAutoChat();loadBotStatus()},8000);
setInterval(function(){if(selectedUser)loadMind(true)},12000);
