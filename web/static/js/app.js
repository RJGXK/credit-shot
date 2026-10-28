/* 企业信用一键截图工具 —— 前端交互
   职责：
     1. 拉目录（站点/采集项/默认参数）并渲染清单；
     2. 收集参数，调用 REST 端点启动/控制任务；
     3. 订阅 SSE，实时把日志与状态画到界面上。 */
'use strict';

const $ = (id) => document.getElementById(id);

const state = {
  catalog: null,
  mode: '单位',        // 单位 / 人员
  running: false,
  waiting: false,
  logAtBottom: true,   // 日志是否跟随底部
  credPlatforms: [],
  credRows: new Map(), // platform -> {enabled, username, password, show}
  captchaKeySet: false, // 本地是否已保存打码服务 API Key
};

const SHOT_MODES = ['原图', '原图+信息条', '原图+日期弹窗', '原图+日期弹窗+信息条'];

/* ------------------------------------------------------------------ 工具 */
function toast(message, kind) {
  const el = $('toast');
  el.textContent = message;
  el.className = 'toast show' + (kind ? ' ' + kind : '');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.className = 'toast'; }, 3200);
}

async function api(path, options) {
  const res = await fetch(path, Object.assign({
    headers: { 'Content-Type': 'application/json' }
  }, options || {}));
  let body = null;
  try { body = await res.json(); } catch (e) { body = null; }
  if (!res.ok) {
    const detail = (body && body.detail) || ('请求失败（' + res.status + '）');
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return body;
}

/* ------------------------------------------------------------------ 目录 */
async function loadCatalog() {
  const catalog = await api('/api/catalog');
  state.catalog = catalog;

  $('outputDir').value = catalog.defaults.output_dir;
  $('browserSel').innerHTML = catalog.browsers
    .map((b) => `<option value="${b}"${b === catalog.defaults.browser ? ' selected' : ''}>${b}</option>`)
    .join('');
  $('shotModeSel').innerHTML = SHOT_MODES
    .map((m) => `<option value="${m}"${m === catalog.defaults.shot_mode ? ' selected' : ''}>${m}</option>`)
    .join('');
  $('paceInput').value = catalog.defaults.pace_seconds;
  $('pdfCheck').checked = !!catalog.defaults.make_pdf;

  state.credPlatforms = catalog.login_platforms || [];
  renderChecklist();
  renderCredRows();
  updateFootNote();
}

function renderChecklist() {
  const box = $('checklist');
  box.innerHTML = '';
  state.catalog.sites.forEach((site) => {
    const block = document.createElement('div');
    block.className = 'site-block';
    block.id = 'site-' + site.key;

    const head = document.createElement('div');
    head.className = 'site-head';
    const all = document.createElement('input');
    all.type = 'checkbox';
    all.title = '全选本组';
    all.addEventListener('change', () => {
      block.querySelectorAll('.step-row input').forEach((cb) => {
        if (!cb.disabled) { cb.checked = all.checked; }
      });
      refreshCounts();
    });
    const name = document.createElement('span');
    name.className = 'site-name';
    name.textContent = site.name;
    name.title = site.name;              // 悬停显示全名
    const siteAll = document.createElement('span');
    siteAll.className = 'site-all';
    siteAll.appendChild(all);
    head.appendChild(name);
    head.appendChild(siteAll);
    block.appendChild(head);

    site.steps.forEach((step) => {
      const row = document.createElement('label');
      row.className = 'step-row';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.value = step.key;
      cb.checked = true;
      cb.dataset.subject = step.subject;
      cb.addEventListener('change', refreshCounts);

      // 阻止原生 label 带来的第二次点击（label 触发两次 click，导致勾选状态反转）
      row.addEventListener('click', (e) => {
        if (e.target !== cb) {
          e.preventDefault();
          if (!cb.disabled) {
            cb.checked = !cb.checked;
            cb.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }
      });

      const no = document.createElement('span');
      no.className = 'step-no';
      no.textContent = step.no;
      const title = document.createElement('span');
      title.className = 'step-label';
      title.textContent = step.title;
      title.title = step.title;          // 窄屏省略后，悬停仍能看到全名
      row.appendChild(cb);
      row.appendChild(no);
      row.appendChild(title);
      block.appendChild(row);
    });

    box.appendChild(block);
  });
  refreshCounts();
  applyMode();
  renderSiteJump();
}

/** 站点快速跳转条。
 *  清单有 7 个站点 28 项，靠滚轮找「中国裁判文书网」很费劲；
 *  给一条快捷栏，点一下直接定位。
 */
function renderSiteJump() {
  const bar = $('siteJump');
  if (!bar) { return; }
  bar.innerHTML = '';
  state.catalog.sites.forEach((site) => {
    const btn = document.createElement('button');
    btn.className = 'jump-btn';
    btn.type = 'button';
    btn.textContent = site.short || site.name;
    btn.title = site.name;
    btn.addEventListener('click', () => jumpToSite(site));
    bar.appendChild(btn);
  });
}

function jumpToSite(site) {
  const box = $('checklist');
  const block = document.getElementById('site-' + site.key);
  if (!box || !block) { return; }
  // 用 rect 差值算偏移，offsetTop 会受 offsetParent 影响而偏掉
  const top = block.getBoundingClientRect().top
            - box.getBoundingClientRect().top + box.scrollTop - 8;
  // 用 auto 而不是 smooth：smooth 滚动期间若卡片头文字变化导致容器高度变化，
  // 滚动终点会被打断，站点块停在半截位置
  box.scrollTo({ top: Math.max(0, top), behavior: 'auto' });
  block.classList.remove('flash');
  void block.offsetWidth;          // 强制重排，让动画能重播
  block.classList.add('flash');
}

/** 当前模式下不适用的采集项置灰并取消勾选 */
function applyMode() {
  const modeKey = state.mode === '单位' ? 'company' : 'person';
  document.querySelectorAll('#checklist .step-row input').forEach((cb) => {
    const subject = cb.dataset.subject;
    const ok = subject === 'either' || subject === modeKey;
    cb.disabled = !ok;
    if (!ok) { cb.checked = false; }
    cb.closest('.step-row').classList.toggle('disabled', !ok);
  });
  refreshCounts();
}

function refreshCounts() {
  const all = Array.from(document.querySelectorAll('#checklist .step-row input'));
  const usable = all.filter((cb) => !cb.disabled);
  const selected = usable.filter((cb) => cb.checked);
  $('countText').textContent =
    `已选 ${selected.length} / ${usable.length} 项（当前模式可用 ${usable.length} 项）`;
}

function selectedKeys() {
  return Array.from(document.querySelectorAll('#checklist .step-row input'))
    .filter((cb) => !cb.disabled && cb.checked)
    .map((cb) => cb.value);
}

/* ------------------------------------------------------------------ 日志 */
function logClass(text) {
  if (/✔|成功|已保存|已提交|完成/.test(text)) return 'log-ok';
  if (/✘|失败|错误|致命/.test(text)) return 'log-error';
  if (/⚠|⏸|跳过|提示/.test(text)) return 'log-warn';
  if (/^[=▌\-→✔✘⏸]/.test(text) || /^\s{2}/.test(text)) return 'log-info';
  return 'log-plain';
}

function appendLog(text) {
  const box = $('logBox');
  const line = document.createElement('div');
  line.className = 'log-line ' + logClass(text);
  line.textContent = text;
  box.appendChild(line);
  if (state.logAtBottom) { box.scrollTop = box.scrollHeight; }
  while (box.childElementCount > 2000) { box.removeChild(box.firstChild); }
}

function clearLog() {
  $('logBox').innerHTML = '';
}

/* ------------------------------------------------------------------ 状态 */
function setRunning(running) {
  state.running = running;
  $('btnStart').disabled = running;
  $('btnStart').textContent = running ? '运行中…' : '开始截图';
  $('btnStop').disabled = !running;
  $('btnSkip').disabled = !running;
  $('btnResume').disabled = !running || !state.waiting;
}

function setWaiting(waiting) {
  state.waiting = waiting;
  $('btnResume').disabled = !state.running || !waiting;
  $('btnResume').classList.toggle('btn-primary', waiting);
  const chip = $('statusChip');
  if (waiting) {
    chip.textContent = '等待处理';
    chip.className = 'chip chip-waiting';
  } else if (state.running) {
    chip.textContent = '运行中';
    chip.className = 'chip chip-running';
  }
}

function updateFootNote() {
  $('footNote').textContent =
    `截图方式：${$('shotModeSel').value} · 浏览器：${$('browserSel').value}` +
    ` · 日期弹窗 = 叠加系统右下角日期/时间面板`;
}

/* ------------------------------------------------------------------ SSE */
function connectEvents() {
  const source = new EventSource('/api/events');
  source.onmessage = (evt) => {
    let payload;
    try { payload = JSON.parse(evt.data); } catch (e) { return; }
    handleEvent(payload.kind, payload.data);
  };
  source.onerror = () => {
    // EventSource 自带重连，这里只提示一次
    $('logHint').textContent = '连接中断，正在重连…';
  };
}

function handleEvent(kind, data) {
  if (kind === 'log') {
    appendLog(String(data));
  } else if (kind === 'status') {
    if (data.state === 'waiting') { setWaiting(true); }
    else if (data.state === 'running') { setWaiting(false); }
    else if (data.state === 'done') {
      setWaiting(false);
      setRunning(false);
      $('statusChip').textContent = '已结束';
      $('statusChip').className = 'chip chip-done';
    }
  } else if (kind === 'done') {
    setRunning(false);
    setWaiting(false);
    $('statusChip').textContent = '已结束';
    $('statusChip').className = 'chip chip-done';
  }
}

/* ------------------------------------------------------------------ 任务 */
async function startRun() {
  const subjects = $('subjectInput').value.split('\n')
    .map((s) => s.trim()).filter(Boolean);
  if (!subjects.length) { toast('请先填写查询主体', 'error'); return; }
  const keys = selectedKeys();
  if (!keys.length) { toast('请至少选择一个采集项', 'error'); return; }

  clearLog();
  setRunning(true);
  $('statusChip').textContent = '运行中';
  $('statusChip').className = 'chip chip-running';
  $('logHint').textContent = '实时推送';

  try {
    await api('/api/run', {
      method: 'POST',
      body: JSON.stringify({
        subjects: subjects,
        step_keys: keys,
        options: {
          output_dir: $('outputDir').value.trim(),
          browser: $('browserSel').value,
          shot_mode: $('shotModeSel').value,
          subject_mode: state.mode,
          pace_seconds: Number($('paceInput').value) || 0,
          make_pdf: $('pdfCheck').checked
        }
      })
    });
  } catch (err) {
    toast(err.message, 'error');
    appendLog('✘ 启动失败：' + err.message);
    setRunning(false);
  }
}

async function sendControl(action) {
  try {
    await api('/api/control/' + action, { method: 'POST' });
  } catch (err) {
    toast(err.message, 'error');
  }
}

/* ------------------------------------------------------------------ 凭据 */
function renderCredRows() {
  const box = $('credRows');
  box.innerHTML = '';
  state.credRows.clear();
  state.credPlatforms.forEach((p) => {
    const row = document.createElement('div');
    row.className = 'cred-row';

    const chkCell = document.createElement('span');
    chkCell.className = 'c-chk';
    const chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.checked = true;
    chkCell.appendChild(chk);

    const nameCell = document.createElement('span');
    nameCell.className = 'c-name';
    nameCell.textContent = p.name;
    nameCell.title = p.hint || '';

    const user = document.createElement('input');
    user.type = 'text';
    user.placeholder = p.account || '账号';

    const pass = document.createElement('input');
    pass.type = 'password';
    pass.placeholder = '密码';

    const eyeCell = document.createElement('span');
    eyeCell.className = 'c-eye';
    const eye = document.createElement('button');
    eye.type = 'button';
    eye.className = 'eye-btn';
    eye.textContent = '👁';
    eye.title = '显示/隐藏明文';
    eye.addEventListener('click', () => {
      const show = pass.type === 'password';
      pass.type = show ? 'text' : 'password';
      eye.textContent = show ? '🚫' : '👁';
    });
    eyeCell.appendChild(eye);

    row.appendChild(chkCell);
    row.appendChild(nameCell);
    row.appendChild(user);
    row.appendChild(pass);
    row.appendChild(eyeCell);
    box.appendChild(row);

    state.credRows.set(p.key, { enabled: chk, username: user, password: pass });
  });
}

function collectCredentials() {
  const out = [];
  state.credRows.forEach((row, key) => {
    out.push({
      platform: key,
      username: row.username.value,
      password: row.password.value,
      enabled: row.enabled.checked
    });
  });
  return out;
}

function applyLoadedCredentials(data) {
  const map = new Map((data.credentials || []).map((c) => [c.platform, c]));
  state.credRows.forEach((row, key) => {
    const saved = map.get(key);
    if (saved) {
      row.username.value = saved.username || '';
      row.enabled.checked = !!saved.enabled;
      // 密码不回显。留空 = 「不修改」，不是「清空」——
      // 之前每点一次「保存到本地」就把已保存的密码抹掉，自动登录随之失效。
      row.password.value = '';
      row.password.placeholder = saved.has_password
        ? '已保存（留空则不修改）' : '密码';
    } else {
      row.password.value = '';
      row.password.placeholder = '密码';
    }
  });
  // 打码 Key 同样不回显，但要让用户看得出「已经配过了」
  const keyInput = $('captchaKey');
  keyInput.value = '';
  keyInput.placeholder = data.captcha_key_set
    ? '已保存（留空则不修改）' : '填入 YesCaptcha API Key';
  state.captchaKeySet = !!data.captcha_key_set;

  const n = data.credentials && data.credentials.length
    ? data.credentials.length : 0;
  $('credSummary').textContent = n ? `已配置 ${n} 个平台账号` : '未配置';
}

async function saveCredentials() {
  try {
    const payload = {
      credentials: collectCredentials(),
      captcha_key: $('captchaKey').value.trim()
    };
    await api('/api/credentials', { method: 'POST', body: JSON.stringify(payload) });
    const blankPwd = payload.credentials.filter((c) => !c.password).length;
    $('credStatus').textContent = '✔ 已保存到本地（明文文件）'
      + (blankPwd ? `；${blankPwd} 个平台的密码留空 = 保持原样` : '');
    $('credSummary').textContent = `已配置 ${payload.credentials.length} 个平台账号`;
    // 保存后刷新一次状态：密码/Key 已是「已保存」状态
    const data = await api('/api/credentials');
    applyLoadedCredentials(data);
  } catch (err) {
    $('credStatus').textContent = '✘ ' + err.message;
  }
}

async function loadCredentials() {
  try {
    const data = await api('/api/credentials/load', { method: 'POST' });
    applyLoadedCredentials(data);
    $('credStatus').textContent = '已从本地载入（密码不回显）';
  } catch (err) {
    $('credStatus').textContent = '✘ ' + err.message;
  }
}

async function testCaptcha() {
  const key = $('captchaKey').value.trim();
  if (!key && !state.captchaKeySet) {
    $('credStatus').textContent = '请先填 API Key';
    return;
  }
  $('credStatus').textContent = '正在测试…';
  try {
    // api_key 传空时后端会用本地已保存的 Key 去测
    const data = await api('/api/captcha/test', {
      method: 'POST', body: JSON.stringify({ api_key: key })
    });
    $('credStatus').textContent = `✔ API Key 可用，余额 ${data.balance.toFixed(2)} 点`;
  } catch (err) {
    $('credStatus').textContent = '✘ ' + err.message;
  }
}

/* ------------------------------------------------------------------ 绑定 */
function bindEvents() {
  $('modeSegment').addEventListener('click', (evt) => {
    const btn = evt.target.closest('.seg');
    if (!btn) return;
    state.mode = btn.dataset.mode;
    document.querySelectorAll('#modeSegment .seg').forEach((b) => {
      b.classList.toggle('active', b === btn);
    });
    $('subjectFormatHint').textContent = state.mode === '单位'
      ? '企业名称|统一社会信用代码' : '人员姓名|身份证号';
    $('modeHint').textContent = state.mode === '单位'
      ? '一行一个，可批量；信用代码可留空，只写企业名称也行'
      : '一行一个，可批量；身份证号填 15 位或 18 位';
    $('statusText').textContent = '查询类型：' + state.mode;
    applyMode();
  });

  $('btnAll').addEventListener('click', () => {
    document.querySelectorAll('#checklist .step-row input').forEach((cb) => {
      if (!cb.disabled) { cb.checked = true; }
    });
    refreshCounts();
  });
  $('btnNone').addEventListener('click', () => {
    document.querySelectorAll('#checklist .step-row input').forEach((cb) => { cb.checked = false; });
    refreshCounts();
  });

  $('btnStart').addEventListener('click', startRun);
  $('btnResume').addEventListener('click', () => sendControl('resume'));
  $('btnSkip').addEventListener('click', () => sendControl('skip'));
  $('btnStop').addEventListener('click', () => sendControl('stop'));

  $('btnSelfcheck').addEventListener('click', async () => {
    clearLog();
    toast('自检进行中…');
    try {
      const data = await api('/api/selfcheck', { method: 'POST' });
      toast(data.ok ? '功能自检全部通过' : '功能自检存在失败项', data.ok ? 'ok' : 'error');
    } catch (err) {
      toast(err.message, 'error');
    }
  });

  $('btnBrowse').addEventListener('click', async () => {
    const path = $('outputDir').value.trim();
    try {
      const data = await api('/api/validate-output', {
        method: 'POST', body: JSON.stringify({ path: path })
      });
      $('outputDir').value = data.path;
      toast('目录可用', 'ok');
    } catch (err) {
      toast(err.message, 'error');
    }
  });

  $('btnOpenDir').addEventListener('click', async () => {
    try {
      await api('/api/open-output', {
        method: 'POST', body: JSON.stringify({ path: $('outputDir').value.trim() })
      });
    } catch (err) {
      toast(err.message, 'error');
    }
  });

  // 用系统浏览器打开界面（软件窗口之外的第二入口）
  $('btnOpenBrowser').addEventListener('click', async () => {
    try {
      await api('/api/open-in-browser', { method: 'POST' });
    } catch (err) {
      toast(err.message, 'error');
    }
  });

  $('shotModeSel').addEventListener('change', updateFootNote);
  $('browserSel').addEventListener('change', updateFootNote);

  $('btnCredentials').addEventListener('click', async () => {
    try {
      const data = await api('/api/credentials');
      applyLoadedCredentials(data);
      $('credStatus').textContent = data.path;
    } catch (err) {
      toast(err.message, 'error');
    }
    $('credDialog').showModal();
  });
  $('btnCredClose').addEventListener('click', () => $('credDialog').close());
  $('btnCredSave').addEventListener('click', saveCredentials);
  $('btnCredLoad').addEventListener('click', loadCredentials);
  $('btnCredTest').addEventListener('click', testCaptcha);

  // 日志滚到底部时自动跟随；用户手动上滚后不再抢视图
  $('logBox').addEventListener('scroll', () => {
    const box = $('logBox');
    state.logAtBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 24;
  });
}

/* ------------------------------------------------------------------ 启动 */
async function main() {
  bindEvents();
  try {
    await loadCatalog();
  } catch (err) {
    toast('加载目录失败：' + err.message, 'error');
  }
  connectEvents();
  setRunning(false);
}

main();
