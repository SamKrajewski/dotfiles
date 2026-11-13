/* TODO Dash frontend. Vanilla JS, no build step. */
(() => {
  'use strict';

  const S = { data: null, tab: 'today', briefDay: null, histGoal: 'all', docKind: 'all', busy: false,
    chats: {}, attach: [],
    open: JSON.parse(localStorage.getItem('todo-dash.open') || '{}') };
  const PRIOS = ['P0', 'P1', 'P2', 'P3'];
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ---------------------------------------------------------------- theme-safe secondary colours
  // The host pushes its theme tokens into the iframe, but its muted/secondary text
  // token can be nearly invisible. Derive every secondary text colour from the
  // *rendered* body text and background instead, so contrast is guaranteed.
  function parseRgb(s) {
    const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)/.exec(s || '');
    if (!m) return null;
    const a = m[4] == null ? 1 : parseFloat(m[4]);
    return { r: +m[1], g: +m[2], b: +m[3], a };
  }
  function applyDerivedColors() {
    const body = getComputedStyle(document.body);
    const fg = parseRgb(body.color);
    let bg = parseRgb(body.backgroundColor);
    if (!bg || bg.a === 0) bg = parseRgb(getComputedStyle(document.documentElement).backgroundColor);
    if (!fg) return;
    if (!bg || bg.a === 0) {
      const lum = 0.2126 * fg.r + 0.7152 * fg.g + 0.0722 * fg.b;
      bg = lum > 128 ? { r: 20, g: 20, b: 20 } : { r: 255, g: 255, b: 255 };
    }
    const mix = (w) => `rgb(${['r', 'g', 'b'].map((k) => Math.round(fg[k] * w + bg[k] * (1 - w))).join(',')})`;
    const root = document.documentElement.style;
    root.setProperty('--muted', mix(0.74));
    root.setProperty('--muted-soft', mix(0.64));
    root.setProperty('--muted-strong', mix(0.86));
    root.setProperty('--bubble-user', mix(0.08));
  }
  applyDerivedColors();
  [200, 800, 2500].forEach((ms) => setTimeout(applyDerivedColors, ms));
  window.addEventListener('message', (e) => { if (e.data && e.data.type === 'theme-change') setTimeout(applyDerivedColors, 0); });

  // ---------------------------------------------------------------- utils
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function el(tag, attrs = {}, ...children) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'html') n.innerHTML = v;
      else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
      else if (['title', 'value', 'placeholder', 'type', 'checked', 'disabled', 'open', 'rows'].includes(k)) n[k] = v;
      else n.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      n.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return n;
  }
  function toast(msg, isError = false) {
    const t = $('#toast');
    t.textContent = msg;
    t.className = 'toast' + (isError ? ' error' : '');
    clearTimeout(toast._h);
    toast._h = setTimeout(() => t.classList.add('hidden'), isError ? 5000 : 2200);
  }
  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso + 'T00:00:00');
    if (isNaN(d)) return iso;
    return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
  }
  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }
  function dueLabel(t) {
    if (t.due_in == null) return null;
    if (t.due_in < 0) return { text: `overdue ${-t.due_in}d`, cls: 'over' };
    if (t.due_in === 0) return { text: 'due today', cls: 'over' };
    if (t.due_in <= 3) return { text: `due in ${t.due_in}d`, cls: 'soon' };
    return { text: `due ${fmtDate(t.due)}`, cls: '' };
  }
  const prioRank = (p) => PRIOS.indexOf(p || 'P2');
  // Collapsible section with remembered open state.
  function section(key, titleNode, bodyNode, { defaultOpen = false, extra = null } = {}) {
    const isOpen = key in S.open ? S.open[key] : defaultOpen;
    const d = el('details', { class: 'card sec', open: isOpen });
    d.append(el('summary', {}, el('span', { class: 'chev' }, '▸'), el('span', { class: 'sec-title' }, titleNode), extra ? el('span', { class: 'sec-extra' }, extra) : null));
    d.append(el('div', { class: 'sec-body' }, bodyNode));
    d.addEventListener('toggle', () => { S.open[key] = d.open; localStorage.setItem('todo-dash.open', JSON.stringify(S.open)); });
    return d;
  }

  // ---------------------------------------------------------------- api
  const sfetch = (url, opts) => (window.sidecar && window.sidecar.fetch ? window.sidecar.fetch(url, opts) : fetch(url, opts));
  async function apiGet(path) {
    const r = await fetch(path, { cache: 'no-store' });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  async function apiPost(path, body, { reload = true, quiet = false } = {}) {
    if (S.busy) return null;
    S.busy = true;
    try {
      const r = await sfetch(path, { method: 'POST', body: JSON.stringify(body || {}) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || r.statusText);
      if (j.message && !quiet) toast(j.message);
      if (reload) await load();
      return j;
    } catch (e) {
      toast(e.message || String(e), true);
      return null;
    } finally {
      S.busy = false;
    }
  }

  // ---------------------------------------------------------------- chat
  // Two conversations with the agent: 'main' is the Chat tab; 'brief' is the discussion
  // thread baked into the brief card, shared by the Today and Brief pages.
  const chatState = (ch) => S.chats[ch] || (S.chats[ch] = { items: [], working: false, conversationId: null, pending: null, seenAgentText: null });
  const attachments = () => S.attach || (S.attach = []);
  function attachToChat(id, { open = true } = {}) {
    if (!attachments().includes(id)) attachments().push(id);
    renderAttachments();
    toast(`${id} attached to chat`);
    if (open) switchTab('chat');
  }
  function renderAttachments() {
    const row = $('#chat-attach');
    row.innerHTML = '';
    const ids = attachments();
    row.classList.toggle('hidden', !ids.length);
    for (const id of ids) {
      const item = findItem(id);
      row.append(el('span', { class: 'pill', title: item ? item.title : id },
        el('span', { class: 'pill-id' }, id), item ? el('span', { class: 'pill-title' }, item.title) : null,
        el('button', { class: 'pill-x', title: 'Remove', onclick: () => { S.attach = ids.filter((x) => x !== id); renderAttachments(); } }, '✕')));
    }
    if (ids.length > 1) row.append(el('button', { class: 'btn ghost small ro', onclick: () => { S.attach = []; renderAttachments(); } }, 'clear'));
  }
  function findItem(id) {
    if (/^G/.test(id)) { for (const g of S.data.goals) { if (g.id === id) return g; for (const s of g.subgoals) if (s.id === id) return s; } return null; }
    return findTask(id);
  }
  async function chatSend(channel, text, attach, { stay = false } = {}) {
    text = (text || '').trim();
    if (!text) return;
    const c = chatState(channel);
    const ids = attach || (channel === 'main' ? attachments().slice() : []);
    const shown = ids.length ? `${text}\n\n📎 ${ids.join(', ')}` : text;
    c.pending = { role: 'user', text: shown, at: new Date().toISOString(), pending: true };
    if (!stay && channel === 'main') switchTab('chat');
    renderChat(channel);
    const r = await apiPost('/api/chat/send', { channel, text, attach: ids }, { reload: false, quiet: true });
    if (!r) { c.pending = null; renderChat(channel); return; }
    if (channel === 'main') { S.attach = []; renderAttachments(); }
    c.working = true;
    setTimeout(() => pollChat(channel), 800);
  }
  async function pollChat(channel) {
    const c = chatState(channel);
    try {
      const r = await apiGet('/api/chat/state?channel=' + channel);
      const prev = c.items.length;
      const wasWorking = c.working;
      Object.assign(c, { items: r.items || [], working: !!r.working, conversationId: r.conversationId || null });
      if (c.pending && c.items.some((m) => m.role === 'user' && m.text.split('\n')[0] === c.pending.text.split('\n')[0])) c.pending = null;
      const nAgent = c.items.filter((m) => m.role === 'agent' && m.kind === 'text').length;
      if (nAgent > (c.seenAgentText || 0)) {
        if (c.seenAgentText != null && channel === 'main' && S.tab !== 'chat') $('#chat-dot').classList.remove('hidden');
        c.seenAgentText = nAgent;
      }
      renderChat(channel);
      if ((wasWorking && !c.working) || (c.items.length !== prev && !c.working)) load();   // the agent may have edited TODO.md
    } catch (e) { /* transient */ }
  }

  // Every chat surface registers its log element with its channel; all surfaces of a
  // channel are re-rendered from the same items.
  const chatPanels = new Map();
  function renderChat(channel) {
    const c = chatState(channel);
    for (const [id, panel] of chatPanels) {
      if (!document.body.contains(panel.log)) { chatPanels.delete(id); continue; }
      if (panel.channel === channel) renderChatLog(panel.log, channel, panel.opts);
    }
    if (channel === 'main') {
      $('#chat-status').textContent = c.conversationId ? (c.working ? 'Agent is working…' : 'Agent is idle') : 'No conversation yet — your first message starts one';
      $('#chat-open').disabled = !c.conversationId;
      $('#chat-new').disabled = !c.conversationId;
    }
    $$(`.chat-mini-status[data-channel="${channel}"]`).forEach((n) => { n.textContent = c.working ? '● agent working' : ''; });
    $$(`.chat-open-link[data-channel="${channel}"]`).forEach((n) => { n.classList.toggle('hidden', !c.conversationId); });
  }
  function groupTurns(items) {
    const turns = [];
    for (const it of items) {
      if (it.role === 'user') turns.push({ role: 'user', item: it });
      else {
        const last = turns[turns.length - 1];
        if (last && last.role === 'agent') last.items.push(it);
        else turns.push({ role: 'agent', items: [it] });
      }
    }
    return turns;
  }
  const TOOL_ICON = { run_command: '⌘', read_file: '📄', write_file: '✍', edit_file: '✍', invoke_subagent: '🤖', search_web: '🔍', moma_search: '🔍', skill_search: '🔍', ask_question: '❓' };
  function renderAgentTurn(turn, { live }) {
    const wrap = el('div', { class: 'turn' });
    const items = turn.items;
    const lastTextIdx = items.map((x) => x.kind).lastIndexOf('text');

    let stepBuf = [];

    function flushSteps() {
      if (!stepBuf.length) return;
      const count = stepBuf.length;
      const hasRunning = live && stepBuf.some((x) => x.kind === 'tool' && x.status === 'running');
      const lastRunning = hasRunning ? stepBuf.filter((x) => x.kind === 'tool' && x.status === 'running').pop() : null;

      const d = el('details', { class: 'steps-fold' });
      const sum = el('summary', { title: `${count} step${count === 1 ? '' : 's'}` },
        el('span', { class: 'chev' }, '▸'),
        hasRunning ? el('span', { class: 'spin' }) : null,
        el('span', { class: 'steps-title' }, hasRunning ? 'thinking…' : 'thinking steps')
      );
      const body = el('div', { class: 'steps-fold-body' });
      stepBuf.forEach((it) => {
        if (it.kind === 'thinking') {
          const td = el('details', { class: 'think' });
          td.append(el('summary', {}, el('span', { class: 'chev' }, '▸'), 'Thinking'), el('div', { class: 'think-body' }, it.text));
          body.append(td);
        } else if (it.kind === 'tool') {
          const row = el('details', { class: `tool ${it.status}` });
          row.append(el('summary', {}, el('span', { class: 'tool-ico' }, TOOL_ICON[it.name] || '•'), el('span', { class: 'tool-label' }, it.label),
            it.status === 'running' ? el('span', { class: 'spin' }) : el('span', { class: `tool-dot ${it.status}` })));
          const tb = el('div', { class: 'tool-body' });
          if (it.detail) tb.append(el('div', { class: 'mono tool-detail' }, it.detail));
          if (it.result) tb.append(el('pre', { class: 'tool-out' }, it.result));
          else if (it.status === 'running') tb.append(el('div', { class: 'muted' }, 'running…'));
          row.append(tb);
          body.append(row);
        } else if (it.kind === 'error') {
          body.append(el('div', { class: 'tool error-row' }, '⚠ ', it.text));
        }
      });
      d.append(sum, body);
      wrap.append(d);
      stepBuf = [];
    }

    items.forEach((it, idx) => {
      if (it.kind === 'thinking' || it.kind === 'tool' || it.kind === 'error') {
        stepBuf.push(it);
      } else if (it.kind === 'text') {
        flushSteps();
        const isFinal = idx === lastTextIdx && !live;
        const b = el('div', { class: 'bubble agent' + (isFinal ? '' : ' interim') });
        b.innerHTML = mdToHtml(it.text); wireMd(b);
        wrap.append(b);
      }
    });
    flushSteps();

    const last = items[items.length - 1];
    if (live && (!last || last.kind !== 'tool' || last.status !== 'running')) {
      wrap.append(el('div', { class: 'bubble agent typing' }, el('span'), el('span'), el('span')));
    }
    const at = last && last.at;
    return el('div', { class: 'msg agent' }, wrap, el('div', { class: 'msg-time' }, live ? 'working…' : fmtTime(at)));
  }
  function renderUserTurn(m) {
    const b = el('div', { class: `bubble user${m.pending ? ' pending' : ''}` });
    const [body, att] = m.text.split('\n\n[Attached from TODO Dash]\n');
    b.textContent = body;
    if (att) b.append(el('div', { class: 'attached' }, '📎 ' + att.split('\n').filter((l) => /^- (?:[TG]\d|brief:)/.test(l)).map((l) => l.slice(2).split(': ')[0]).join(', ')));
    return el('div', { class: 'msg user' }, b, el('div', { class: 'msg-time' }, m.pending ? 'sending…' : fmtTime(m.at)));
  }
  function renderChatLog(log, channel, { empty = false, compact = false } = {}) {
    const c = chatState(channel);
    const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
    const openStates = new Set($$('details[open]', log).map((d) => d.dataset.key).filter(Boolean));
    log.innerHTML = '';
    let turns = groupTurns(c.items || []);
    if (c.pending) turns.push({ role: 'user', item: c.pending });
    if (compact) turns = turns.slice(-8);
    if (!turns.length && empty) {
      log.append(el('div', { class: 'chat-empty' },
        el('p', {}, 'A dedicated conversation with the agent about your TODO list. It reads the skill, your workspace and your edits here, and keeps context between messages.'),
        el('div', { class: 'row' }, ...[
          ['What should I focus on today?', 'what should I focus on today, and why?'],
          ['Triage proposals', 'walk me through the proposed items one by one so I can accept or reject each'],
          ['Set up my goals', 'help me set up my 2–5 mainline goals and what is due soon'],
          ['Run the daily todo', 'run the daily run now and show me the brief'],
        ].map(([label, text]) => el('button', { class: 'btn ghost small ro', onclick: () => chatSend('main', text) }, label)))));
    }
    if (!turns.length && compact) log.append(el('div', { class: 'chat-empty' }, 'Discuss this brief with the agent: accept or reject its proposals, question a focus item, tell it what it got wrong. The thread continues across days.'));
    turns.forEach((t, i) => {
      if (t.role === 'user') { log.append(renderUserTurn(t.item)); return; }
      const live = c.working && i === turns.length - 1 && !c.pending;
      log.append(renderAgentTurn(t, { live }));
    });
    if (c.working && c.pending) log.append(el('div', { class: 'msg agent' }, el('div', { class: 'bubble agent typing' }, el('span'), el('span'), el('span'))));
    $$('details', log).forEach((d, i) => { d.dataset.key = 'd' + i; if (openStates.has('d' + i)) d.open = true; });
    if (stick) log.scrollTop = log.scrollHeight;
  }
  // A chat surface (log + composer) bound to a channel. attachFn() adds context ids on send.
  function chatPanel(id, channel, { attachFn = () => [], placeholder = 'Message the agent…' } = {}) {
    const log = el('div', { class: 'chat-log compact' });
    const ta = el('textarea', { rows: 2, class: 'ro', placeholder });
    ta.value = (S.drafts && S.drafts[id]) || '';
    ta.addEventListener('input', () => { (S.drafts = S.drafts || {})[id] = ta.value; });
    const send = () => { const v = ta.value.trim(); if (!v) return; ta.value = ''; if (S.drafts) S.drafts[id] = ''; chatSend(channel, v, attachFn(), { stay: true }); };
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
    chatPanels.set(id, { channel, log, opts: { compact: true } });
    renderChatLog(log, channel, { compact: true });
    return el('div', { class: 'chat-panel' }, log, el('div', { class: 'chat-input' }, ta, el('button', { class: 'btn ro', onclick: send }, 'Send')));
  }
  // The brief's discussion dropdown: one shared 'brief' thread, shown inside the brief card
  // on Today and on the Brief page.
  function briefDiscussion(id, day) {
    const key = 'discuss.' + id;
    const d = el('details', { class: 'discuss', open: S.open[key] ?? false });
    const c = chatState('brief');
    d.append(el('summary', {}, el('span', { class: 'chev' }, '▸'), el('span', { class: 'sec-title' }, 'Discuss this brief'),
      el('span', { class: 'muted chat-mini-status', 'data-channel': 'brief' }, c.working ? '● agent working' : ''),
      el('span', { class: 'spacer' }),
      el('span', { class: 'muted', style: 'font-size:12.5px' }, `📎 brief ${day}`),
      el('a', { href: '#', class: 'chat-open-link' + (c.conversationId ? '' : ' hidden'), 'data-channel': 'brief', style: 'font-size:12.5px;margin-left:8px', title: 'Open this thread in Jetski',
        onclick: (e) => { e.preventDefault(); e.stopPropagation(); if (chatState('brief').conversationId) openConversation(chatState('brief').conversationId); } }, 'open in Jetski')));
    d.append(chatPanel(id, 'brief', { attachFn: () => [`brief:${day}`], placeholder: 'Reply to this brief… (“accept T21”, “T7 is done, drop it”, “why is T12 in focus?”)' }));
    d.addEventListener('toggle', () => { S.open[key] = d.open; localStorage.setItem('todo-dash.open', JSON.stringify(S.open)); if (d.open) pollChat('brief'); });
    return d;
  }
  chatPanels.set('main', { channel: 'main', log: $('#chat-log'), opts: { empty: true, compact: false } });
  $('#chat-send').addEventListener('click', () => { const t = $('#chat-text'); chatSend('main', t.value); t.value = ''; });
  $('#chat-text').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#chat-send').click(); } });
  $('#chat-open').addEventListener('click', () => chatState('main').conversationId && openConversation(chatState('main').conversationId));
  $('#chat-new').addEventListener('click', () => {
    openModal('Start new conversation', el('div', {},
      el('p', {}, 'Start a fresh conversation in the Chat tab? The current conversation will stay in your Jetski history.'),
      el('div', { class: 'row', style: 'margin-top:14px' },
        el('button', { class: 'btn ghost small ro', onclick: closeModal }, 'Cancel'),
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn danger small ro', onclick: async () => {
          closeModal();
          try {
            await apiPost('/api/chat/reset', { channel: 'main' }, { reload: false });
            S.chats.main = null;
            chatState('main');
            renderChat('main');
            toast('Started a fresh conversation');
          } catch (e) {
            toast('Failed to reset: ' + e.message, true);
          }
        } }, 'Start fresh'))));
  });
  setInterval(() => {
    if (document.hidden) return;
    if (S.tab === 'chat' || chatState('main').working) pollChat('main');
    if (S.tab === 'today' || S.tab === 'brief' || chatState('brief').working) pollChat('brief');
  }, 2500);

  const runDaily = () => chatSend('main', 'Run my daily TODO now (the skill\'s "Daily run" mode; one subagent per subskill, type "self", model "flash"). Show me the brief here when it is done.');

  // ---------------------------------------------------------------- load & render
  async function load() {
    try {
      const d = await apiGet('/api/state');
      S.data = d;
      render();
    } catch (e) {
      showBanner('Cannot load state: ' + (e.message || e), true);
    }
  }
  function showBanner(msg, isError) {
    const b = $('#banner');
    if (!msg) { b.classList.add('hidden'); return; }
    b.textContent = msg;
    b.className = 'banner' + (isError ? ' error' : '');
  }

  function render() {
    const d = S.data;
    if (!d) return;
    if (d.error) {
      showBanner(d.error, true);
      $('#date-line').textContent = d.home || '';
      return;
    }
    $('#date-line').textContent = `${d.weekday} ${d.today}`;
    const c = d.counts;
    const run = d.run;
    const chips = $('#chips');
    chips.innerHTML = '';
    const chip = (label, val, cls, onclick) => chips.append(el('span', { class: 'chip ' + (cls || '') + (onclick ? ' click' : ''), onclick }, el('b', {}, val), ' ', label));
    chip('open', c.open, '', () => switchTab('goals'));
    if (c.p0) chip('P0', c.p0, 'bad');
    if (c.overdue) chip('overdue', c.overdue, 'bad');
    if (c.waiting) chip('waiting', c.waiting);
    if (c.proposed) chip('proposed', c.proposed, 'warn', () => switchTab('inbox'));
    chips.append(el('span', { class: 'chip ' + (run.ran_today ? 'ok' : ''), title: run.last_run ? `Last run ${run.last_run.date || ''}` : 'no run recorded' },
      run.ran_today ? '✓ ran today' : (run.last_run && run.last_run.date ? `last run ${run.last_run.date}` : 'never run')));
    if (run.locked) showBanner('A todo run is in progress: edits are disabled until it finishes.', false);
    else if (d.issues && d.issues.length) showBanner(`TODO.md has ${d.issues.length} lint issue(s): ${d.issues[0].message || d.issues[0]}`, true);
    else showBanner(null);
    $('#inbox-count').textContent = (d.proposed.length + d.parked.length) || '';

    renderToday();
    renderGoals();
    renderInbox();
    renderHistory();
    renderDocs();
    renderBrief();
    if (run.locked) $$('#main .btn, #main select, #main input').forEach((n) => { if (!n.classList.contains('ro')) n.disabled = true; });
  }

  // ---------------------------------------------------------------- shared widgets
  function allOpenTasks() {
    const d = S.data;
    const out = [];
    for (const g of d.goals) {
      out.push(...g.tasks.map((t) => ({ ...t, goalTitle: g.title })));
      for (const s of g.subgoals) out.push(...s.tasks.map((t) => ({ ...t, goalTitle: g.title, subTitle: s.title })));
    }
    out.push(...d.other);
    return out.filter((t) => t.state === ' ');
  }
  function goalOptions(selected) {
    const opts = [el('option', { value: '' }, 'Other tasks')];
    for (const g of S.data.goals) opts.push(el('option', { value: g.id, selected: g.id === selected }, `${g.id} ${g.title}`));
    return opts;
  }
  function prioSelect(current, onchange, extraClass = '') {
    const s = el('select', { class: `prio ${current || 'P2'} ${extraClass}`, title: 'Priority' },
      ...PRIOS.map((p) => el('option', { value: p, selected: p === current }, p)));
    s.addEventListener('change', () => onchange(s.value));
    return s;
  }
  function findTask(id) {
    const d = S.data;
    for (const g of d.goals) { for (const t of g.tasks) if (t.id === id) return t; for (const s of g.subgoals) for (const t of s.tasks) if (t.id === id) return t; }
    return [...d.other, ...d.proposed, ...d.parked].find((t) => t.id === id) || null;
  }
  function openSource(t) {
    const s = t.src || {};
    if (s.conversation) return openConversation(s.conversation);
    if (s.url) return openInPane(s.url);
    toast(s.raw || 'no source link');
  }
  function taskRow(t, opts = {}) {
    const closed = t.state !== ' ';
    const due = dueLabel(t);
    const meta = el('div', { class: 'tmeta' });
    if (due) meta.append(el('span', { class: `tag due ${due.cls}` }, due.text));
    if (t.waiting) meta.append(el('span', { class: 'tag wait' }, `⏳ ${t.waiting.split(' since ')[0]}${t.nudge && t.nudge <= S.data.today ? ' · nudge due' : ''}`));
    if (t.pinned) meta.append(el('span', { class: 'tag', title: 'Pinned: the skill will not change this priority' }, '📌'));
    const ab = assignBadge(t); if (ab) meta.append(ab);
    if (t.next) meta.append(el('span', { class: 'next' }, '→ ', t.next));
    if (opts.showGoal && t.goalTitle) meta.append(el('span', { class: 'muted' }, t.goalTitle));

    const ctl = el('div', { class: 'tctl' });
    if (!opts.readonly) {
      ctl.append(prioSelect(t.priority, (p) => apiPost('/api/task/set', { id: t.id, priority: p })));
      ctl.append(taskMenu(t));
    } else {
      ctl.append(el('span', { class: `pbadge ${t.priority}` }, t.priority + (t.pinned ? '!' : '') + (t.provisional ? '?' : '')));
    }
    const cb = el('input', { type: 'checkbox', checked: closed, title: closed ? 'Marked done; the next run logs and removes it. Untick to undo.' : 'Mark done (the next run logs it)' });
    cb.addEventListener('change', () => apiPost('/api/task/set', { id: t.id, state: cb.checked ? 'x' : ' ' }));
    if (opts.readonly || t.section === 'Proposed') cb.disabled = true;
    const titleNode = el('span', { class: 'ttitle', title: 'Details & context', onclick: () => taskDetails(t) }, t.title, ' ', ctxMark(t.id));
    return el('div', { class: 'task' + (t.parent ? ' sub' : '') + (closed ? ' closed' : ''), 'data-id': t.id },
      cb,
      el('div', { class: 'tmain' }, el('div', {}, el('span', { class: 'tid' }, t.id), titleNode), meta.childNodes.length ? meta : null),
      ctl);
  }
  // Context editor: private notes per goal/task, stored in <home>/context/<ID>.md and
  // handed to the agent whenever the item is attached to the chat.
  function contextEditor(id) {
    const cur = (S.data.item_context || {})[id] || '';
    const ta = el('textarea', { rows: 5, class: 'ro', placeholder: 'Background, amendments, decisions, people, links… Not shown in the list; the agent reads it whenever it works on this item.' });
    ta.value = cur;
    const status = el('span', { class: 'muted', style: 'font-size:12.5px' }, cur ? 'saved' : '');
    let dirty = false;
    const save = async () => {
      if (!dirty) return;
      const r = await apiPost('/api/context/set', { id, text: ta.value }, { quiet: true });
      if (r) { dirty = false; status.textContent = 'saved'; }
    };
    ta.addEventListener('input', () => { dirty = true; status.textContent = 'unsaved'; });
    ta.addEventListener('blur', save);
    return el('div', { class: 'ctx' },
      el('div', { class: 'row' }, el('span', { class: 'ctx-label' }, 'Context for the agent'), el('span', { class: 'spacer' }), status,
        el('button', { class: 'btn ghost small ro', onclick: save }, 'Save')),
      ta);
  }
  function taskDetails(t) {
    const s = t.src || {};
    const rows = [
      ['Priority', t.priority + (t.pinned ? ' (pinned)' : '') + (t.provisional ? ' (provisional)' : '')],
      ['Section', t.section + (t.goal ? ` · ${t.goal}${t.subgoal ? ' / ' + t.subgoal : ''}` : '')],
      ['Due', t.due ? fmtDate(t.due) : '—'],
      ['Next', t.next || '—'],
      ['Waiting', t.waiting ? `${t.waiting}${t.nudge ? ' · nudge ' + fmtDate(t.nudge) : ''}` : '—'],
      ['Draft', t.draft || '—'],
      ['Note', t.note || '—'],
      ['Source', s.raw || '—'],
    ];
    if (s.conversation) rows.push(['Conversation', s.conversation]);
    const body = el('div', {},
      el('dl', { class: 'kv' }, ...rows.flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, v)])),
      contextEditor(t.id),
      (t.section === 'Goals' || t.section === 'Other tasks') ? assignmentSection(t) : null,
      el('div', { class: 'row', style: 'margin-top:12px' },
        (s.url || s.conversation) ? el('button', { class: 'btn ghost small ro', onclick: () => openSource(t) }, s.conversation ? 'Open conversation' : 'Open source') : null,
        t.draft ? el('button', { class: 'btn ghost small ro', onclick: () => openFile(t.draft, 'Draft for ' + t.id) }, 'Open draft') : null,
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn small ro', onclick: () => { closeModal(); attachToChat(t.id); } }, 'Add to chat')));
    openModal(`${t.id} · ${t.title}`, body);
  }
  function goalDetails(g, parent) {
    const rows = [
      ['Priority', (g.priority || `${parent ? parent.priority : 'P2'} (inherited)`) + (g.pinned ? ' (pinned)' : '')],
      ['Due', g.due ? fmtDate(g.due) : '—'],
      ['Done when', g.done_when || '—'],
      ['Progress', `${g.progress.done} done · ${g.progress.open} open${g.progress.dropped ? ' · ' + g.progress.dropped + ' dropped' : ''}`],
    ];
    const body = el('div', {},
      el('dl', { class: 'kv' }, ...rows.flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, v)])),
      contextEditor(g.id),
      el('div', { class: 'row', style: 'margin-top:12px' }, el('span', { class: 'spacer' }),
        el('button', { class: 'btn small ro', onclick: () => { closeModal(); attachToChat(g.id); } }, 'Add to chat')));
    openModal(`${g.id} · ${g.title}`, body);
  }
  const ctxMark = (id) => ((S.data.item_context || {})[id] ? el('span', { class: 'ctxmark', title: 'Has context notes for the agent' }, '✎') : null);

  // ---- assignments: a task delegated to its own agent conversation
  const assignmentOf = (id) => (S.data && S.data.assignments && S.data.assignments[id] && S.data.assignments[id].conversationId ? S.data.assignments[id] : null);
  function assignBadge(t) {
    const a = assignmentOf(t.id);
    if (!a) return null;
    const state = a.working ? 'working' : a.asked ? 'needs you' : a.last_text ? 'replied' : 'assigned';
    return el('span', { class: `tag agent ${a.working ? 'working' : ''} ${a.asked ? 'asked' : ''}`, title: (a.last_text || 'Open the agent\'s conversation').slice(0, 300), onclick: (e) => { e.stopPropagation(); openConversation(a.conversationId); } },
      a.working ? el('span', { class: 'spin' }) : '🤖', ' ', state);
  }
  function assignDialog(t) {
    const ta = el('textarea', { rows: 3, class: 'ro', placeholder: 'Optional instructions, e.g. “just draft it, don’t send”, “use the approach from the design doc”, “keep it under an hour”' });
    ta.style.width = '100%';
    const ctx = (S.data.item_context || {})[t.id];
    openModal(`Assign ${t.id} to an agent`, el('div', {},
      el('p', {}, el('b', {}, t.title)),
      el('p', { class: 'muted' }, 'Starts a dedicated Jetski conversation for this task. The agent gets the task line, your context notes', ctx ? ' (present)' : ' (none yet — consider adding some first)', ' and the linked source, does what it can from this machine, prepares-and-asks before anything reaches other people, and records progress back into the todo.'),
      ta,
      el('div', { class: 'row', style: 'margin-top:10px' }, el('span', { class: 'spacer' }),
        el('button', { class: 'btn', onclick: async () => { closeModal(); const r = await apiPost('/api/task/assign', { id: t.id, instructions: ta.value }); if (r && r.conversationId) toast(`${t.id} assigned — watch the 🤖 badge`); } }, 'Assign'))));
  }
  function nudgeDialog(t, a) {
    const ta = el('textarea', { rows: 3, class: 'ro', placeholder: 'Message for the agent working on this task…' });
    ta.style.width = '100%';
    openModal(`Nudge the agent on ${t.id}`, el('div', {},
      a.last_text ? el('div', { class: 'md last-reply', html: mdToHtml(a.last_text) }) : el('p', { class: 'muted' }, 'No reply yet.'),
      ta,
      el('div', { class: 'row', style: 'margin-top:10px' }, el('button', { class: 'btn ghost small ro', onclick: () => openConversation(a.conversationId) }, 'Open conversation'), el('span', { class: 'spacer' }),
        el('button', { class: 'btn', onclick: async () => { if (!ta.value.trim()) return; closeModal(); await apiPost('/api/task/nudge', { id: t.id, text: ta.value }); } }, 'Send'))));
  }
  function assignmentSection(t) {
    const a = assignmentOf(t.id);
    if (!a) return el('div', { class: 'row', style: 'margin-top:12px' }, el('button', { class: 'btn ghost small ro', onclick: () => { closeModal(); assignDialog(t); } }, '🤖 Assign to agent…'));
    const body = el('div', { class: 'asg' },
      el('div', { class: 'row' }, el('span', { class: 'ctx-label' }, '🤖 Assigned to an agent'), el('span', { class: 'muted' }, `since ${fmtDate((a.started || '').slice(0, 10))}`), a.working ? el('span', { class: 'spin' }) : null, el('span', { class: 'spacer' }),
        el('button', { class: 'btn ghost small ro', onclick: () => openConversation(a.conversationId) }, 'Open'),
        el('button', { class: 'btn ghost small ro', onclick: () => { closeModal(); nudgeDialog(t, a); } }, 'Nudge'),
        el('button', { class: 'btn ghost small ro', onclick: async () => { closeModal(); await apiPost('/api/task/unassign', { id: t.id }); } }, 'Unassign')),
      a.instructions ? el('div', { class: 'muted', style: 'font-size:12.5px;margin-top:4px' }, 'Instructions: ', a.instructions) : null,
      a.last_text ? el('div', { class: 'md last-reply', html: mdToHtml(a.last_text) }) : el('div', { class: 'muted', style: 'margin-top:6px' }, a.working ? 'Working on it…' : 'No reply yet.'));
    wireMd(body);
    return body;
  }
  function taskMenu(t) {
    const wrap = el('div', { class: 'menu' });
    const btn = el('button', { class: 'btn ghost small', title: 'More' }, '⋯');
    const list = el('div', { class: 'menu-list hidden' });
    const item = (label, fn, cls = '') => list.append(el('button', { class: cls, onclick: () => { list.classList.add('hidden'); fn(); } }, label));
    item('Add to chat', () => attachToChat(t.id));
    item('Details & context', () => taskDetails(t));
    if (t.src && (t.src.url || t.src.conversation)) {
      item(t.src.conversation ? 'Open conversation' : 'Open source', () => openSource(t));
    }
    if (t.section === 'Proposed') {
      item('Accept into…', () => acceptDialog(t));
      item('Reject (dismiss)', () => rejectDialog(t), 'danger');
    } else if (t.section === 'Parked') {
      item('Unpark into…', () => acceptDialog(t, 'Unpark'));
      item('Drop', () => apiPost('/api/task/set', { id: t.id, state: '-' }), 'danger');
    } else {
      const asg = assignmentOf(t.id);
      if (asg) {
        item(asg.working ? 'Agent is working… (open)' : 'Open the agent\'s conversation', () => openConversation(asg.conversationId));
        item('Nudge the agent…', () => nudgeDialog(t, asg));
        item('Unassign agent', () => apiPost('/api/task/unassign', { id: t.id }));
      } else {
        item('Assign to agent…', () => assignDialog(t));
      }
      item(t.pinned ? 'Unpin priority' : 'Pin priority', () => apiPost('/api/task/set', { id: t.id, pinned: !t.pinned }));
      item('Move to goal…', () => acceptDialog(t, 'Move'));
      item('Park', () => apiPost('/api/task/park', { id: t.id }));
      item('Drop', () => apiPost('/api/task/set', { id: t.id, state: '-' }), 'danger');
    }
    btn.addEventListener('click', (e) => { e.stopPropagation(); $$('.menu-list').forEach((m) => m !== list && m.classList.add('hidden')); list.classList.toggle('hidden'); });
    wrap.append(btn, list);
    return wrap;
  }
  document.addEventListener('click', () => $$('.menu-list').forEach((m) => m.classList.add('hidden')));

  function acceptDialog(t, verb = 'Accept') {
    const sel = el('select', {}, ...goalOptions(t.goal));
    openModal(`${verb} ${t.id}`, el('div', {},
      el('p', {}, t.title),
      el('div', { class: 'row' }, el('span', { class: 'muted' }, 'Into'), sel, el('span', { class: 'spacer' }),
        el('button', { class: 'btn', onclick: async () => { closeModal(); await apiPost('/api/task/move', { id: t.id, goal: sel.value || null }); } }, verb))));
  }
  function rejectDialog(t) {
    const inp = el('input', { type: 'text', placeholder: 'why (e.g. not mine, already done)', value: 'not mine' });
    inp.style.width = '100%';
    openModal(`Reject ${t.id}`, el('div', {},
      el('p', {}, t.title),
      el('p', { class: 'muted' }, 'Its source reference goes to ## Dismissed so it is not proposed again.'),
      inp,
      el('div', { class: 'row', style: 'margin-top:10px' }, el('span', { class: 'spacer' }),
        el('button', { class: 'btn danger', onclick: async () => { closeModal(); await apiPost('/api/task/reject', { id: t.id, why: inp.value }); } }, 'Reject'))));
  }
  function quickAdd(goalId) {
    const inp = el('input', { type: 'text', placeholder: goalId ? `Add a task to ${goalId}…` : 'Add a task…' });
    const prio = prioSelect('P2', () => {});
    const due = el('input', { type: 'date', title: 'Due (optional)' });
    const go = async () => {
      if (!inp.value.trim()) return;
      const r = await apiPost('/api/task/add', { title: inp.value.trim(), priority: prio.value, goal: goalId || null, due: due.value || null });
      if (r) { inp.value = ''; due.value = ''; }
    };
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    return el('div', { class: 'quick-add' }, inp, prio, due, el('button', { class: 'btn small', onclick: go }, 'Add'));
  }

  // ---------------------------------------------------------------- today
  function renderToday() {
    const d = S.data;
    const root = $('#tab-today');
    root.innerHTML = '';
    const open = allOpenTasks();

    const focus = open.slice().sort((a, b) => prioRank(a.priority) - prioRank(b.priority) || ((a.due_in ?? 9999) - (b.due_in ?? 9999)) || a.id.localeCompare(b.id, undefined, { numeric: true })).slice(0, 5);
    const focusBody = el('div', {});
    if (!focus.length) focusBody.append(el('div', { class: 'empty' }, d.goals.length ? 'Nothing open.' : 'No goals or tasks yet. Use the Chat tab to set up your goals, or add tasks under Goals.'));
    focus.forEach((t, i) => {
      const due = dueLabel(t);
      focusBody.append(el('div', { class: 'focus-item' },
        el('span', { class: 'focus-n' }, i + 1),
        el('div', { style: 'flex:1' },
          el('div', {}, el('span', { class: `pbadge ${t.priority}` }, t.priority), ' ', el('span', { class: 'tid' }, t.id), el('span', { class: 'ttitle', onclick: () => taskDetails(t) }, t.title)),
          el('div', { class: 'tmeta' }, t.next ? el('span', { class: 'next' }, '→ ', t.next) : null, due ? el('span', { class: `tag due ${due.cls}` }, due.text) : null, t.goalTitle ? el('span', { class: 'muted' }, t.goalTitle) : null)),
        el('input', { type: 'checkbox', title: 'Mark done', onchange: (e) => apiPost('/api/task/set', { id: t.id, state: e.target.checked ? 'x' : ' ' }) })));
    });
    root.append(section('today.focus', 'Focus', focusBody, { defaultOpen: true, extra: focus.length ? `${focus.length}` : '' }));

    const due = open.filter((t) => t.due_in != null && t.due_in <= 7).sort((a, b) => a.due_in - b.due_in);
    if (due.length) root.append(section('today.due', 'Due this week', el('div', {}, ...due.map((t) => taskRow(t, { readonly: true, showGoal: true }))), { extra: `${due.length}` }));

    const waiting = open.filter((t) => t.waiting);
    if (waiting.length) {
      const nudgeDue = (t) => t.nudge && t.nudge <= d.today;
      const n = waiting.filter(nudgeDue).length;
      root.append(section('today.waiting', 'Waiting on others', el('div', {}, ...waiting.sort((a, b) => (nudgeDue(b) - nudgeDue(a))).map((t) => taskRow(t, { readonly: true, showGoal: true }))), { extra: n ? `${n} follow-up due` : `${waiting.length}`, defaultOpen: n > 0 }));
    }

    if (d.proposed.length) root.append(section('today.proposed', 'Proposed by sources', el('div', {}, ...d.proposed.slice(0, 5).map((t) => taskRow(t)), d.proposed.length > 5 ? el('div', { class: 'muted', style: 'padding-top:6px' }, `+${d.proposed.length - 5} more in Inbox`) : null), { extra: `${d.proposed.length}`, defaultOpen: true }));

    if (d.briefs.length) {
      const day = d.briefs[0];
      const holder = el('div', { class: 'md' }, el('div', { class: 'muted' }, 'loading…'));
      root.append(section('today.brief', day === d.today ? "Today's brief: needs your input" : `Latest brief (${fmtDate(day)})`,
        el('div', {}, holder, briefDiscussion('today-brief', day)),
        { defaultOpen: true, extra: el('a', { href: '#', onclick: (e) => { e.preventDefault(); e.stopPropagation(); switchTab('brief'); } }, 'full brief') }));
      apiGet('/api/file?path=' + encodeURIComponent(`briefs/${day}.md`)).then((f) => {
        const sec = extractSections(f.text, ['Needs your input', 'Prepared for you', 'Follow-ups due', 'Schedule']);
        holder.innerHTML = sec ? mdToHtml(sec) : '<div class="empty">Nothing needs your input.</div>';
        wireMd(holder);
      }).catch(() => { holder.innerHTML = ''; });
    }

    const run = d.run;
    const srcs = run.sources || {};
    const kv = el('dl', { class: 'kv' },
      el('dt', {}, 'Last run'), el('dd', {}, run.last_run ? `${run.last_run.date || ''} ${run.last_run.mode ? '(' + run.last_run.mode + ')' : ''}` : 'never'),
      el('dt', {}, 'Sources'), el('dd', {}, Object.keys(srcs).length ? Object.entries(srcs).map(([k, v]) => `${k}: ${v.status || v.last_status || '?'}`).join(' · ') : '—'),
      el('dt', {}, 'Workspace'), el('dd', { class: 'mono' }, d.home));
    root.append(section('today.runs', 'Runs & sources', el('div', {}, kv, el('div', { class: 'row', style: 'margin-top:10px' },
      el('button', { class: 'btn small ro', onclick: runDaily }, run.ran_today ? 'Rerun the daily todo' : 'Run daily todo'))), { extra: run.ran_today ? 'ran today' : '' }));
  }

  // ---------------------------------------------------------------- goals
  function progressBar(p) {
    const total = p.open + p.done;
    return el('div', { class: 'prog' },
      el('div', { class: 'progress' }, el('div', { style: `width:${p.percent}%` })),
      el('div', { class: 'progress-label' }, el('span', {}, total ? `${p.done} of ${total} done${p.dropped ? ' · ' + p.dropped + ' dropped' : ''}` : 'no tasks yet'), el('span', {}, total ? `${p.percent}%` : '')));
  }
  function goalHead(g, isSub, parent) {
    const due = g.due ? el('span', { class: `tag due ${g.due_in < 0 ? 'over' : g.due_in <= 7 ? 'soon' : ''}` }, `due ${fmtDate(g.due)}`) : null;
    return el('div', { class: 'goal-head', onclick: (e) => e.stopPropagation() },
      el('span', { class: 'gid' }, g.id),
      el('span', { class: 'gtitle', title: 'Details & context', onclick: () => goalDetails(g, parent) }, g.title, ' ', ctxMark(g.id)),
      due,
      g.pinned ? el('span', { class: 'tag', title: 'Pinned priority' }, '📌') : null,
      prioSelect(g.priority || (parent && parent.priority) || 'P2', (p) => apiPost('/api/goal/set', { id: g.id, priority: p }), g.inherits_priority ? 'inherit' : ''),
      goalMenu(g, isSub, parent));
  }
  function goalMenu(g, isSub, parent) {
    const wrap = el('div', { class: 'menu' });
    const btn = el('button', { class: 'btn ghost small', title: 'More' }, '⋯');
    const list = el('div', { class: 'menu-list hidden' });
    const item = (label, fn, cls = '') => list.append(el('button', { class: cls, onclick: () => { list.classList.add('hidden'); fn(); } }, label));
    item('Add to chat', () => attachToChat(g.id));
    item('Details & context', () => goalDetails(g, parent));
    item(g.pinned ? 'Unpin priority' : 'Pin priority', () => apiPost('/api/goal/set', { id: g.id, pinned: !g.pinned }));
    if (!isSub) item('Park this goal (via agent)', () => chatSend('main', `park goal ${g.id} (${g.title}) with its tasks`, [g.id]));
    btn.addEventListener('click', (e) => { e.stopPropagation(); $$('.menu-list').forEach((m) => m !== list && m.classList.add('hidden')); list.classList.toggle('hidden'); });
    wrap.append(btn, list);
    return wrap;
  }
  function renderGoals() {
    const d = S.data;
    const root = $('#tab-goals');
    root.innerHTML = '';
    if (!d.goals.length) root.append(el('div', { class: 'card' }, el('div', { class: 'empty' }, 'No goals yet.'), el('button', { class: 'btn small ro', onclick: () => chatSend('main', 'help me set up my 2–5 mainline goals and what is due soon') }, 'Set up goals with the agent')));
    d.goals.forEach((g, gi) => {
      const body = el('div', {});
      g.tasks.forEach((t) => body.append(taskRow(t)));
      for (const s of g.subgoals) {
        const sbody = el('div', {});
        s.tasks.forEach((t) => sbody.append(taskRow(t)));
        if (!s.tasks.length) sbody.append(el('div', { class: 'empty' }, 'no open tasks'));
        const sd = el('details', { class: 'subgoal', open: S.open['sub.' + s.id] ?? false });
        sd.append(el('summary', {}, el('span', { class: 'chev' }, '▸'), goalHead(s, true, g)), progressBar(s.progress), sbody);
        sd.addEventListener('toggle', () => { S.open['sub.' + s.id] = sd.open; localStorage.setItem('todo-dash.open', JSON.stringify(S.open)); });
        body.append(sd);
      }
      if (!g.tasks.length && !g.subgoals.length) body.append(el('div', { class: 'empty' }, 'No open tasks: this goal has no next step.'));
      if (g.closed && g.closed.length) {
        const det = el('details', { class: 'closed-list' }, el('summary', { class: 'muted' }, `${g.closed.length} closed`));
        g.closed.slice(0, 20).forEach((c) => det.append(el('div', { class: 'hist-row' }, el('span', { class: `verb ${c.how}` }, c.how), el('span', { class: 'tid' }, c.id), el('span', {}, c.title), el('span', { class: 'muted', style: 'margin-left:auto' }, c.date))));
        body.append(det);
      }
      body.append(quickAdd(g.id));
      const card = el('details', { class: 'card goal', open: S.open['goal.' + g.id] ?? (gi === 0) });
      card.append(el('summary', {}, el('span', { class: 'chev' }, '▸'), goalHead(g, false)),
        g.done_when ? el('div', { class: 'done-when' }, 'Done when: ', g.done_when) : null,
        progressBar(g.progress), body);
      card.addEventListener('toggle', () => { S.open['goal.' + g.id] = card.open; localStorage.setItem('todo-dash.open', JSON.stringify(S.open)); });
      root.append(card);
    });
    const other = el('div', {});
    d.other.forEach((t) => other.append(taskRow(t)));
    if (!d.other.length) other.append(el('div', { class: 'empty' }, 'none'));
    other.append(quickAdd(null));
    root.append(section('goals.other', 'Other tasks', other, { extra: `${d.other.length}`, defaultOpen: !d.goals.length }));
    if (d.unparsed && d.unparsed.length) {
      root.append(section('goals.unparsed', 'Free-form lines', el('div', {}, el('div', { class: 'muted' }, 'The next run turns these into tasks.'), ...d.unparsed.map((u) => el('div', { class: 'mono' }, `${u.section || ''}: ${u.text}`))), { extra: `${d.unparsed.length}` }));
    }
  }

  // ---------------------------------------------------------------- inbox
  function renderInbox() {
    const d = S.data;
    const root = $('#tab-inbox');
    root.innerHTML = '';
    const prop = el('div', {});
    d.proposed.forEach((t) => prop.append(taskRow(t)));
    if (!d.proposed.length) prop.append(el('div', { class: 'empty' }, 'nothing waiting'));
    root.append(section('inbox.proposed', 'Proposed', prop, { defaultOpen: true, extra: `${d.proposed.length}` }));
    const park = el('div', {});
    d.parked.forEach((t) => park.append(taskRow(t)));
    if (!d.parked.length) park.append(el('div', { class: 'empty' }, 'nothing parked'));
    root.append(section('inbox.parked', 'Parked', park, { extra: `${d.parked.length}` }));
    const dis = el('div', {});
    d.dismissed.forEach((x) => dis.append(el('div', { class: 'hist-row' }, el('span', { class: 'muted' }, x.date), el('span', { class: 'mono', style: 'flex:1' }, x.ref), el('span', { class: 'muted' }, x.why))));
    if (!d.dismissed.length) dis.append(el('div', { class: 'empty' }, 'none'));
    root.append(section('inbox.dismissed', 'Dismissed', dis, { extra: `${d.dismissed.length}` }));
  }

  // ---------------------------------------------------------------- history
  function renderHistory() {
    const d = S.data;
    const root = $('#tab-history');
    root.innerHTML = '';
    const goalSel = el('select', { class: 'ro' }, el('option', { value: 'all' }, 'All goals'), el('option', { value: 'none' }, 'No goal'), ...d.goals.map((g) => el('option', { value: g.id }, `${g.id} ${g.title}`)));
    goalSel.value = S.histGoal;
    goalSel.addEventListener('change', () => { S.histGoal = goalSel.value; renderHistory(); });
    root.append(el('div', { class: 'filters' }, goalSel));

    const hist = d.history.filter((h) => S.histGoal === 'all' || (S.histGoal === 'none' ? !h.goal : h.goal === S.histGoal));
    const closed = el('div', {});
    hist.slice(0, 100).forEach((h) => closed.append(el('div', { class: 'hist-row' },
      el('span', { class: `verb ${h.closed.how}` }, h.closed.how), el('span', { class: 'tid' }, h.id), el('span', { style: 'flex:1' }, h.title || ''),
      h.goal ? el('span', { class: 'tag' }, h.goal + (h.subgoal ? '/' + h.subgoal.split('.')[1] : '')) : null,
      el('span', { class: 'muted' }, h.closed.date || ''))));
    if (!hist.length) closed.append(el('div', { class: 'empty' }, 'nothing closed yet'));
    root.append(section('hist.closed', 'Closed tasks', closed, { defaultOpen: true, extra: `${hist.length}` }));

    const tl = el('div', { class: 'timeline' });
    for (const e of d.log) {
      const entry = el('div', { class: 'entry' }, el('div', { class: 'edate' }, `${e.date} ${e.weekday}`));
      for (const b of e.bullets) {
        if (S.histGoal !== 'all' && b.verb !== 'sources') {
          const ids = b.items.map((i) => i.id).filter(Boolean);
          const keep = ids.some((id) => { const rec = d.history.find((h) => h.id === id); const g = rec ? rec.goal : (findTask(id) || {}).goal; return S.histGoal === 'none' ? !g : g === S.histGoal; });
          if (ids.length && !keep) continue;
        }
        entry.append(el('div', {}, el('span', { class: `verb ${b.verb}` }, b.verb), ' ', ...b.items.flatMap((it, i) => [i ? el('span', { class: 'muted' }, ' · ') : null, it.id ? el('span', { class: 'tid' }, it.id + ' ') : null, it.text])));
      }
      if (entry.children.length > 1) tl.append(entry);
    }
    root.append(section('hist.log', 'Log', tl.children.length ? tl : el('div', { class: 'empty' }, 'no log entries yet'), { extra: `${d.log.length} days` }));
  }

  // ---------------------------------------------------------------- docs
  const KIND_ICON = { gdoc: '📄', drive: '🗂', gmail: '✉️', calendar: '📅', cl: '🔧', conversation: '💬', draft: '📝', link: '🔗' };
  function renderDocs() {
    const d = S.data;
    const root = $('#tab-docs');
    root.innerHTML = '';
    const kinds = Array.from(new Set(d.documents.map((x) => x.kind)));
    const sel = el('select', { class: 'ro' }, el('option', { value: 'all' }, 'All kinds'), ...kinds.map((k) => el('option', { value: k }, `${KIND_ICON[k] || ''} ${k}`)));
    sel.value = kinds.includes(S.docKind) ? S.docKind : 'all';
    sel.addEventListener('change', () => { S.docKind = sel.value; renderDocs(); });
    root.append(el('div', { class: 'filters' }, sel));
    const list = el('div', {});
    const docs = d.documents.filter((x) => S.docKind === 'all' || x.kind === S.docKind);
    for (const x of docs) {
      const row = el('div', { class: 'doc' }, el('span', { class: 'ico' }, KIND_ICON[x.kind] || '🔗'));
      const body = el('div', { style: 'flex:1;min-width:0' });
      if (x.kind === 'conversation') body.append(el('a', { href: '#', class: 'dtitle', onclick: (e) => { e.preventDefault(); openConversation(x.url.replace('conversation://', '')); } }, x.title));
      else if (x.kind === 'draft') body.append(el('a', { href: '#', class: 'dtitle', onclick: (e) => { e.preventDefault(); openFile(x.url.slice(6), x.title); } }, x.title));
      else body.append(el('a', { href: x.url, target: '_blank', rel: 'noopener', class: 'dtitle' }, x.title), ' ', el('button', { class: 'btn ghost small ro', title: 'Open in a side pane', onclick: () => openInPane(x.url) }, '⧉'));
      body.append(el('div', { class: 'dmeta' }, [x.via, x.date].filter(Boolean).join(' · ')));
      row.append(body);
      if (x.tasks.length) row.append(el('div', { class: 'tasks' }, ...x.tasks.map((id) => el('span', { class: 'tchip', title: (findTask(id) || {}).title || '', onclick: () => jumpToTask(id) }, id))));
      list.append(row);
    }
    if (!docs.length) list.append(el('div', { class: 'empty' }, 'No linked documents yet. Tasks collected from Docs, mail or conversations will show up here.'));
    root.append(section('docs.list', 'Documents', list, { defaultOpen: true, extra: `${docs.length}` }));

    const bd = el('div', {});
    d.briefs.forEach((b) => bd.append(el('div', { class: 'doc' }, el('span', { class: 'ico' }, '🗞'), el('a', { href: '#', class: 'dtitle', onclick: (e) => { e.preventDefault(); S.briefDay = b; switchTab('brief'); } }, `Brief ${b}`))));
    d.drafts.forEach((x) => bd.append(el('div', { class: 'doc' }, el('span', { class: 'ico' }, '📝'), el('div', {}, el('a', { href: '#', class: 'dtitle', onclick: (e) => { e.preventDefault(); openFile(x.path, x.path); } }, x.subject || x.path.split('/').pop()), el('div', { class: 'dmeta' }, [x.kind, x.for, x.to, x.day].filter(Boolean).join(' · '))))));
    if (!d.briefs.length && !d.drafts.length) bd.append(el('div', { class: 'empty' }, 'none yet'));
    root.append(section('docs.briefs', 'Briefs & drafts', bd, { extra: `${d.briefs.length + d.drafts.length}` }));
  }
  function openConversation(id) {
    if (window.sidecar && window.sidecar.ui) window.sidecar.ui.toggleConversation(id);
    else toast('conversation://' + id);
  }
  function openInPane(url) {
    if (window.sidecar && window.sidecar.ui) window.sidecar.ui.toggleAuxPane({ tabType: 'browserView', uri: url });
    else window.open(url, '_blank', 'noopener');
  }
  async function openFile(rel, title) {
    try {
      const f = await apiGet('/api/file?path=' + encodeURIComponent(rel));
      const body = el('div', { class: 'md', html: mdToHtml(f.text) });
      wireMd(body);
      openModal(title || rel, body);
    } catch (e) { toast(e.message, true); }
  }
  function jumpToTask(id) {
    switchTab('goals');
    const n = $(`.task[data-id="${id}"]`);
    if (n) {
      const det = n.closest('details'); if (det) det.open = true;
      const outer = det && det.parentElement ? det.parentElement.closest('details') : null; if (outer) outer.open = true;
      n.scrollIntoView({ behavior: 'smooth', block: 'center' }); n.style.outline = '2px solid var(--pri)'; setTimeout(() => (n.style.outline = ''), 1600);
    } else toast(`${id} is not in Goals (closed, proposed or parked)`);
  }

  // ---------------------------------------------------------------- brief
  function renderBrief() {
    const d = S.data;
    const root = $('#tab-brief');
    root.innerHTML = '';
    if (!d.briefs.length) { root.append(el('div', { class: 'card' }, el('div', { class: 'empty' }, 'No briefs yet. Run the daily todo to get the first one.'), el('button', { class: 'btn small ro', onclick: runDaily }, 'Run daily todo'))); return; }
    if (!S.briefDay || !d.briefs.includes(S.briefDay)) S.briefDay = d.briefs[0];
    const sel = el('select', { class: 'ro' }, ...d.briefs.map((b) => el('option', { value: b }, b)));
    sel.value = S.briefDay;
    sel.addEventListener('change', () => { S.briefDay = sel.value; renderBrief(); });
    const holder = el('div', { class: 'card md' }, el('div', { class: 'muted' }, 'loading…'));
    root.append(el('div', { class: 'filters' }, sel, el('span', { class: 'spacer' }), el('button', { class: 'btn ghost small ro', onclick: () => openFile('context.md', 'context.md') }, 'context.md'), el('button', { class: 'btn ghost small ro', onclick: () => openFile('TODO.md', 'TODO.md (raw)') }, 'TODO.md')), holder);
    apiGet('/api/file?path=' + encodeURIComponent(`briefs/${S.briefDay}.md`)).then((f) => { holder.innerHTML = mdToHtml(f.text); wireMd(holder); }).catch((e) => { holder.innerHTML = `<div class="empty">${esc(e.message)}</div>`; });

    const day = S.briefDay;
    root.append(chatPanel('brief', {
      attachFn: () => [`brief:${day}`],
      placeholder: 'Reply to this brief… (“accept T21”, “T7 is done, drop it”, “why is T12 in focus?”)',
      note: `📎 brief ${day} attached`,
    }));
  }

  // ---------------------------------------------------------------- markdown (tiny)
  function inline(s) {
    let h = esc(s);
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    h = h.replace(/\[([^\]]+)\]\(file:\/\/[^)\s]+\)/g, '$1');
    h = h.replace(/&lt;(https?:\/\/[^&\s]+)&gt;/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    h = h.replace(/(^|[\s(])(https?:\/\/[^\s)<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    h = h.replace(/conversation:\/\/([0-9a-f-]{36})/g, '<a href="#" class="conv-link" data-id="$1">conversation</a>');
    h = h.replace(/(^|[^\w/="'-])(T\d+)(?![\w-])/g, '$1<span class="tid-link" data-id="$2">$2</span>');
    return h;
  }
  function mdToHtml(text) {
    const lines = String(text || '').replace(/\r/g, '').split('\n');
    let out = '', list = null, para = [], inCode = false, inFm = false;
    const flushP = () => { if (para.length) { out += `<p>${inline(para.join(' '))}</p>`; para = []; } };
    const flushL = () => { if (list) { out += `</${list}>`; list = null; } };
    lines.forEach((raw, i) => {
      const l = raw.replace(/\s+$/, '');
      if (i === 0 && l === '---') { inFm = true; return; }
      if (inFm) { if (l === '---') { inFm = false; } return; }
      if (l.startsWith('```')) { flushP(); flushL(); inCode = !inCode; out += inCode ? '<pre>' : '</pre>'; return; }
      if (inCode) { out += esc(l) + '\n'; return; }
      if (/^<!--.*-->$/.test(l.trim())) return;
      const h = /^(#{1,6})\s+(.*)$/.exec(l);
      if (h) { flushP(); flushL(); out += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`; return; }
      if (/^\s*\|/.test(l)) { flushP(); flushL(); if (!/^\s*\|[\s:-]+\|/.test(l)) out += `<div class="mono">${inline(l.replace(/^\s*\||\|\s*$/g, '').replace(/\s*\|\s*/g, ' · '))}</div>`; return; }
      const ul = /^\s*[-*+]\s+(.*)$/.exec(l);
      const ol = /^\s*\d+[.)]\s+(.*)$/.exec(l);
      if (ul || ol) { flushP(); const kind = ul ? 'ul' : 'ol'; if (list !== kind) { flushL(); out += `<${kind}>`; list = kind; } out += `<li>${inline((ul || ol)[1])}</li>`; return; }
      if (/^\s*>\s?/.test(l)) { flushP(); flushL(); out += `<p class="muted">${inline(l.replace(/^\s*>\s?/, ''))}</p>`; return; }
      if (!l.trim()) { flushP(); flushL(); return; }
      flushL(); para.push(l);
    });
    flushP(); flushL();
    return out;
  }
  function extractSections(text, names) {
    const lines = String(text || '').split('\n');
    let keep = false, out = [];
    for (const l of lines) {
      const h = /^##\s+(.*)$/.exec(l);
      if (h) { keep = names.some((n) => h[1].trim().toLowerCase().startsWith(n.toLowerCase())); }
      if (keep) out.push(l);
    }
    const s = out.join('\n').trim();
    return s && !/^## [^\n]*\nNothing\.?$/.test(s) ? s : '';
  }
  function wireMd(root) {
    $$('.tid-link', root).forEach((n) => n.addEventListener('click', () => { const t = findTask(n.dataset.id); if (t) taskDetails(t); else jumpToTask(n.dataset.id); }));
    $$('.conv-link', root).forEach((n) => n.addEventListener('click', (e) => { e.preventDefault(); openConversation(n.dataset.id); }));
  }

  // ---------------------------------------------------------------- modal, tabs, boot
  function openModal(title, body) { $('#modal-title').textContent = title; const b = $('#modal-body'); b.innerHTML = ''; b.append(body); $('#modal').classList.remove('hidden'); }
  function closeModal() { $('#modal').classList.add('hidden'); }
  $('#modal-close').addEventListener('click', closeModal);
  $('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });
  function switchTab(name) {
    S.tab = name;
    $$('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    $$('.tab').forEach((t) => t.classList.toggle('active', t.id === 'tab-' + name));
    if (name === 'brief') renderBrief();
    if (name === 'chat') { $('#chat-dot').classList.add('hidden'); pollChat('main'); setTimeout(() => $('#chat-text').focus(), 50); }
  }
  $$('#tabs button').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));
  $('#btn-refresh').addEventListener('click', () => { load(); pollChat('main'); pollChat('brief'); });
  (() => {
    const list = $('#more-menu');
    const item = (label, fn) => list.append(el('button', { onclick: () => { list.classList.add('hidden'); fn(); } }, label));
    item('Run daily todo', runDaily);
    item('Triage proposals with the agent', () => chatSend('main', 'walk me through the proposed items one by one so I can accept or reject each'));
    item('Open TODO.md (raw)', () => openFile('TODO.md', 'TODO.md (raw)'));
    item('Open context.md', () => openFile('context.md', 'context.md'));
    $('#btn-more').addEventListener('click', (e) => { e.stopPropagation(); list.classList.toggle('hidden'); });
  })();

  const userIsTyping = () => {
    const a = document.activeElement;
    if (a && $('#main').contains(a) && (a.tagName === 'INPUT' || a.tagName === 'SELECT' || a.tagName === 'TEXTAREA')) return true;
    return $$('#main input[type=text]').some((i) => i.value.trim());
  };
  load();
  pollChat('main');
  pollChat('brief');
  setInterval(() => { if (!document.hidden && !S.busy && $('#modal').classList.contains('hidden') && !userIsTyping()) load(); }, 20000);
  setInterval(() => { const a = S.data && S.data.assignments; if (a && Object.values(a).some((x) => x.working) && !document.hidden && !S.busy && !userIsTyping()) load(); }, 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { load(); pollChat('main'); pollChat('brief'); } });
})();
