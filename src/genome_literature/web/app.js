'use strict';

const PER_PAGE = 20;
const HEADERS = {'X-Requested-With': '3DGenomeHub', 'Content-Type': 'application/json'};
const TRACK_NAMES = {ml: 'AI / ML', computational: '计算方法', experimental: '实验与生物学'};
const TASK_LABEL = {interpret: 'AI 解读', summary: '多篇总结', compare: '对比分析', review: '综述', gaps: '研究空白与选题', ask: '文献问答', chat: 'AI 讨论'};
const SUGGESTIONS = {
  selection: ['这些文献分别解决了什么问题？核心方法有何不同？', '它们使用了哪些数据集和评估指标？', '哪些结论彼此一致，哪些存在分歧？', '如果我要复现其中一篇，应该选哪篇？为什么？'],
  library: ['用深度学习从 DNA 序列预测 Hi-C 接触图有哪些代表性方法？', '单细胞 Hi-C 数据补全/增强有哪些方法？各自思路是什么？', '环挤出（loop extrusion）模型的主要实验证据有哪些？', 'TAD 边界识别有哪些计算方法？如何评估？'],
  filtered: ['概括当前筛选结果中的主要研究方向', '这些文献中最常用的模型架构是什么？各有什么优缺点？', '当前筛选结果里有哪些值得关注的新方法？'],
};

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const store = {
  get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { } },
};
const defaultFilters = () => ({q: '', track: '', cat: '', method: '', source: '', yFrom: 0, yTo: 9999, onlyNew: false, onlyPre: false, onlyCur: false, onlyAbs: false, onlyPicked: false});

const S = {
  papers: [], byId: new Map(), stats: {}, newIds: new Set(), f: defaultFilters(), sort: 'relevance', page: 1, view: [],
  showZh: store.get('showZh', false), basket: store.get('basket', []), ai: {configured: false, presets: []},
  notes: [], notedIds: new Set(),
};
const C = {messages: [], contextIds: [], papers: [], scope: store.get('chatScope', 'selection'), busy: false, controller: null};
const R = {task: '', ids: [], question: '', text: '', think: '', refs: [], papers: [], note: null, controller: null, title: '', kind: '', basis: '', model: ''};
let poll = null;
let renderTimer = null;

async function getJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }
async function postJSON(url, body) {
  const r = await fetch(url, {method: 'POST', headers: HEADERS, body: JSON.stringify(body || {})});
  return r.json();
}

function toast(text) {
  const t = $('toast'); t.textContent = text; t.classList.add('show');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove('show'), 2400);
}

/* ---------------------------------------------------------------- markdown */

function citeHTML(group) {
  const ns = [];
  for (const part of group.split(/\s*(?:[,，、]|and)\s*/)) {
    const b = part.split(/\s*[-–—~]\s*/).map(Number).filter(n => n > 0);
    if (b.length === 2 && b[1] > b[0] && b[1] - b[0] <= 50) { for (let n = b[0]; n <= b[1]; n++) ns.push(n); }
    else ns.push(...b);
  }
  return `<a class="cite" data-ns="${ns.join(',')}">[${esc(group)}]</a>`;
}

function mdInline(text) {
  const codes = [];
  let s = esc(text).replace(/`([^`]+)`/g, (m, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\*)/g, '$1<em>$2</em>');
  s = s.replace(/\[(\d{1,3}(?:\s*(?:[-–—~,，、]|and)\s*\d{1,3})*)\](?!\()/g, (m, g) => citeHTML(g));
  return s.replace(/\u0000(\d+)\u0000/g, (m, i) => `<code>${codes[+i]}</code>`);
}

function splitRow(line) {
  let t = line.trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|')) t = t.slice(0, -1);
  return t.split('|').map(c => c.trim());
}

function md(src) {
  const lines = String(src || '').replace(/\r/g, '').split('\n');
  const out = [];
  const lists = [];
  let para = [];
  const flush = () => { if (para.length) { out.push(`<p>${mdInline(para.join('\n')).replace(/\n/g, '<br>')}</p>`); para = []; } };
  const closeLists = (indent = -1) => { while (lists.length && lists[lists.length - 1].indent > indent) out.push(`</li></${lists.pop().type}>`); };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m;
    if (/^\s*```/.test(line)) {
      flush(); closeLists();
      const code = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
      out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
      continue;
    }
    if (!line.trim()) { flush(); if (lists.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i + 1] || '')) continue; closeLists(); continue; }
    if ((m = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/))) { flush(); closeLists(); const lv = Math.min(m[1].length, 4); out.push(`<h${lv}>${mdInline(m[2])}</h${lv}>`); continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); closeLists(); out.push('<hr>'); continue; }
    if (/^\s*>/.test(line)) {
      flush(); closeLists();
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ''));
      i--;
      out.push(`<blockquote>${md(quote.join('\n'))}</blockquote>`);
      continue;
    }
    if (line.includes('|') && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1] || '')) {
      flush(); closeLists();
      const head = splitRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(splitRow(lines[i++]));
      i--;
      out.push('<div class="table-wrap"><table><thead><tr>' + head.map(c => `<th>${mdInline(c)}</th>`).join('') + '</tr></thead><tbody>' +
        rows.map(r => '<tr>' + head.map((_, k) => `<td>${mdInline(r[k] || '')}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>');
      continue;
    }
    if ((m = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/))) {
      flush();
      const indent = m[1].replace(/\t/g, '    ').length;
      const type = /\d/.test(m[2]) ? 'ol' : 'ul';
      const start = type === 'ol' ? parseInt(m[2], 10) : 1;
      const top = lists[lists.length - 1];
      if (!top || indent > top.indent) {
        out.push(`<${type}${type === 'ol' && start !== 1 ? ` start="${start}"` : ''}><li>`);
        lists.push({type, indent});
      } else {
        closeLists(indent);
        const cur = lists[lists.length - 1];
        if (cur && cur.indent === indent && cur.type === type) out.push('</li><li>');
        else {
          if (cur && cur.indent === indent) out.push(`</li></${lists.pop().type}>`);
          out.push(`<${type}${type === 'ol' && start !== 1 ? ` start="${start}"` : ''}><li>`);
          lists.push({type, indent});
        }
      }
      out.push(mdInline(m[3]));
      continue;
    }
    if (lists.length) { out.push(' ' + mdInline(line.trim())); continue; }
    para.push(line.trim());
  }
  flush(); closeLists();
  return out.join('');
}

/* ------------------------------------------------------------------ papers */

async function loadAll() {
  const [papers, stats] = await Promise.all([getJSON('/api/papers'), getJSON('/api/stats')]);
  S.papers = papers; S.stats = stats; S.newIds = new Set(stats.new_ids || []);
  S.byId = new Map(papers.map(p => [p.id, p]));
  S.basket = S.basket.filter(id => S.byId.has(id));
  $('ver').textContent = stats.version ? 'v' + stats.version : '';
  renderFacets(); apply(); renderBasket(); renderChat();
}

function renderFacets() {
  const s = S.stats;
  const tracks = [['', '全部'], ...Object.keys(s.by_track || {}).map(k => [k, TRACK_NAMES[k] || k])];
  $('tracks').innerHTML = tracks.map(([k, name]) => `<button class="chip${S.f.track === k ? ' on' : ''}" data-track="${esc(k)}">${esc(name)}</button>`).join('');
  const desc = s.category_descriptions || {};
  $('cats').innerHTML = Object.keys(s.by_category || {}).map(c =>
    `<div class="item${S.f.cat === c ? ' on' : ''}" data-cat="${esc(c)}" title="${esc(desc[c] || c)}">${esc(c)}</div>`).join('') || '<span class="hint">暂无文献</span>';
  $('methods').innerHTML = Object.keys(s.by_method || {}).map(m =>
    `<div class="item${S.f.method === m ? ' on' : ''}" data-method="${esc(m)}">${esc(m)}</div>`).join('') || '<span class="hint">暂无</span>';
  const src = $('source'), cur = S.f.source;
  src.innerHTML = '<option value="">全部数据库</option>' + Object.keys(s.by_source || {}).map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join('');
  src.value = cur;
  const years = Object.keys(s.by_year || {}).sort((a, b) => b - a);
  for (const id of ['yFrom', 'yTo']) {
    const el = $(id), v = el.value;
    el.innerHTML = `<option value="">${id === 'yFrom' ? '起' : '止'}</option>` + years.map(y => `<option>${y}</option>`).join('');
    el.value = v;
  }
}

function tokens(q) { return [...q.matchAll(/"([^"]+)"|(\S+)/g)].map(m => (m[1] || m[2]).toLowerCase()); }

function searchScore(p, terms) {
  const title = [p.title, p.title_zh].join(' ').toLowerCase();
  const tags = [...(p.categories || []), ...(p.dl_methods || []), ...(p.tools || []), ...(p.keywords || [])].join(' ').toLowerCase();
  const other = [p.abstract, p.abstract_zh, (p.authors || []).join(' '), p.journal, p.doi].join(' ').toLowerCase();
  let score = 0;
  for (const t of terms) {
    if (title.includes(t)) score += 3; else if (tags.includes(t)) score += 2; else if (other.includes(t)) score += 1; else return -1;
  }
  return score;
}

function apply() {
  const f = S.f, terms = tokens(f.q), picked = new Set(S.basket);
  const rows = [];
  for (const p of S.papers) {
    if (f.track && p.track !== f.track) continue;
    if (f.cat && !(p.categories || []).includes(f.cat)) continue;
    if (f.method && !(p.dl_methods || []).includes(f.method)) continue;
    if (f.source && !(p.sources || [p.source]).includes(f.source)) continue;
    if ((p.year || 0) < f.yFrom || (p.year || 0) > f.yTo) continue;
    if (f.onlyNew && !S.newIds.has(p.id)) continue;
    if (f.onlyPre && !p.is_preprint) continue;
    if (f.onlyCur && !p.curated) continue;
    if (f.onlyAbs && !p.abstract) continue;
    if (f.onlyPicked && !picked.has(p.id)) continue;
    let score = 0;
    if (terms.length) { score = searchScore(p, terms); if (score < 0) continue; }
    rows.push([score + (p.relevance || 0) / 100, p]);
  }
  const by = {
    relevance: (a, b) => b[0] - a[0] || (b[1].date || '').localeCompare(a[1].date || ''),
    newest: (a, b) => (b[1].date || '').localeCompare(a[1].date || ''),
    oldest: (a, b) => (a[1].date || '').localeCompare(b[1].date || ''),
    cited: (a, b) => (b[1].citations || 0) - (a[1].citations || 0),
    title: (a, b) => (a[1].title || '').localeCompare(b[1].title || ''),
  };
  rows.sort(by[S.sort]);
  S.view = rows.map(r => r[1]);
  const active = [f.track && TRACK_NAMES[f.track], f.cat, f.method, f.source, f.q && `“${f.q}”`].filter(Boolean);
  $('info').textContent = S.papers.length ? `找到 ${S.view.length} 篇` + (active.length ? ' · ' + active.join(' · ') : '') : '文献库为空';
  render();
}

function authorsShort(p) {
  const a = p.authors || [];
  return a.length > 3 ? a.slice(0, 3).join(', ') + ' et al.' : a.join(', ') || '作者未知';
}

function card(p) {
  const picked = S.basket.includes(p.id);
  const badges = [`<span class="b ${esc(p.track)}">${esc(TRACK_NAMES[p.track] || p.track)}</span>`];
  if (S.newIds.has(p.id)) badges.push('<span class="b new">新增</span>');
  if (p.is_preprint) badges.push('<span class="b pre">预印本</span>');
  if (p.curated) badges.push('<span class="b cur">里程碑</span>');
  if (S.notedIds.has(p.id)) badges.push('<span class="b noted" title="已有 AI 解读，点击“AI 解读”查看">已解读</span>');
  if (S.showZh && p.zh_needs_review) badges.push(`<span class="b review" title="${esc((p.zh_issues || []).join('\n'))}">译文待校对</span>`);
  const tags = (p.categories || []).map(c => `<span class="tag" data-cat="${esc(c)}">${esc(c)}</span>`)
    .concat((p.dl_methods || []).map(m => `<span class="tag m" data-method="${esc(m)}">${esc(m)}</span>`)).join('');
  const links = [];
  if (p.doi) links.push(`<a href="https://doi.org/${esc(p.doi)}" target="_blank" rel="noopener">DOI</a>`);
  if (p.pmid) links.push(`<a href="https://pubmed.ncbi.nlm.nih.gov/${esc(p.pmid)}/" target="_blank" rel="noopener">PubMed</a>`);
  if (p.arxiv_id) links.push(`<a href="https://arxiv.org/abs/${esc(p.arxiv_id)}" target="_blank" rel="noopener">arXiv</a>`);
  if (p.pdf_url) links.push(`<a href="${esc(p.pdf_url)}" target="_blank" rel="noopener">PDF</a>`);
  links.push(`<a href="https://scholar.google.com/scholar?q=${encodeURIComponent(p.title || '')}" target="_blank" rel="noopener">Scholar</a>`);
  const zh = S.showZh && p.title_zh;
  const trBtn = !p.title_zh ? `<button class="act" data-tr="${esc(p.id)}">中文翻译</button>` : (!S.showZh ? '<button class="act" data-trtoggle="1">显示中文</button>' : '');
  const cites = p.citations ? ` · 被引 ${p.citations}` : '';
  return `<article class="card${picked ? ' picked' : ''}" data-id="${esc(p.id)}">
    <div class="card-top">
      <label class="pick"><input type="checkbox" data-pick="${esc(p.id)}"${picked ? ' checked' : ''}> 加入研读</label>
      <div class="badges">${badges.join('')}</div>
      <span class="year">${esc(p.year || '')}</span>
    </div>
    <h2>${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : esc(p.title)}</h2>
    ${zh ? `<div class="zh-title" lang="zh-CN">${esc(p.title_zh)}</div>` : ''}
    <div class="meta">${esc(authorsShort(p))} · <i>${esc(p.journal || '—')}</i> · ${esc(p.date || p.year || '')}${cites}</div>
    <div class="tags">${tags}</div>
    ${p.abstract ? `<p class="abs" title="点击展开 / 收起">${esc(p.abstract)}</p>` : ''}
    ${zh && p.abstract_zh ? `<p class="abs zh" lang="zh-CN" title="点击展开 / 收起">${esc(p.abstract_zh)}</p>` : ''}
    <div class="card-actions">
      <button class="act ai" data-interpret="${esc(p.id)}">✦ AI 解读</button>
      <button class="act" data-discuss="${esc(p.id)}">讨论这篇</button>
      ${trBtn}
      <span class="links">${links.join('')}</span>
    </div>
  </article>`;
}

function render() {
  const pages = Math.max(1, Math.ceil(S.view.length / PER_PAGE));
  S.page = Math.min(S.page, pages);
  const slice = S.view.slice((S.page - 1) * PER_PAGE, S.page * PER_PAGE);
  $('list').innerHTML = slice.length ? slice.map(card).join('')
    : `<div class="empty">${S.papers.length ? '没有符合当前条件的文献。' : '文献库为空 —— 点击右上角“更新文献”，或在“更多”中选择“回溯检索全部年份”。'}</div>`;
  const btn = (p, label, on) => `<button data-page="${p}" class="${on ? 'on' : ''}" ${p < 1 || p > pages ? 'disabled' : ''}>${label}</button>`;
  let html = '';
  if (pages > 1) {
    html += btn(S.page - 1, '‹ 上一页');
    for (let i = 1; i <= pages; i++) {
      if (i === 1 || i === pages || Math.abs(i - S.page) <= 2) html += btn(i, i, i === S.page);
      else if (Math.abs(i - S.page) === 3) html += '<button disabled>…</button>';
    }
    html += btn(S.page + 1, '下一页 ›');
  }
  $('pager').innerHTML = html;
}

function setFilter(key, value) { S.f[key] = S.f[key] === value ? '' : value; S.page = 1; renderFacets(); apply(); }
function pageIds() { return S.view.slice((S.page - 1) * PER_PAGE, S.page * PER_PAGE).map(p => p.id); }

/* ------------------------------------------------------------ reading list */

function saveBasket() { store.set('basket', S.basket); renderBasket(); }
function toggleBasket(id, on) {
  const has = S.basket.includes(id);
  if (on === undefined) on = !has;
  if (on && !has) S.basket.push(id);
  if (!on && has) S.basket = S.basket.filter(x => x !== id);
  saveBasket();
  const el = document.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
  if (el) { el.classList.toggle('picked', on); const cb = el.querySelector('[data-pick]'); if (cb) cb.checked = on; }
}
function addToBasket(ids) {
  let added = 0;
  for (const id of ids) if (!S.basket.includes(id) && S.byId.has(id)) { S.basket.push(id); added++; }
  saveBasket(); render();
  toast(added ? `已加入 ${added} 篇，研读清单共 ${S.basket.length} 篇` : '这些文献已在研读清单中');
}

function renderBasket() {
  const n = S.basket.length;
  $('basketCount').textContent = n; $('fabCount').textContent = n;
  $('basket').innerHTML = n ? S.basket.map((id, i) => {
    const p = S.byId.get(id) || {title: id};
    return `<div class="bitem"><span class="n">${i + 1}.</span><span class="t" data-open="${esc(id)}" title="${esc(p.title)}">${esc(p.title)}${p.year ? ` <span class="hint">(${esc(p.year)})</span>` : ''}</span><button class="x" data-unpick="${esc(id)}" title="移出">×</button></div>`;
  }).join('') : '<div class="basket-empty">研读清单为空<br>在左侧文献卡片上勾选“加入研读”，<br>或点击下方按钮批量加入当前检索结果。</div>';
}

/* ------------------------------------------------------------------- panel */

function setTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.tab === name));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === 'pane-' + name));
  $('chatForm').classList.toggle('on', name === 'chat');
  if (name === 'notes') loadNotes();
  if (name === 'chat') setTimeout(() => $('chatInput').focus(), 50);
}
function openPanel(tab) { $('aiPanel').classList.add('open'); if (tab) setTab(tab); }

/* ---------------------------------------------------------------- settings */

async function loadAISettings() {
  try { S.ai = await getJSON('/api/ai/settings'); } catch (e) { S.ai = {configured: false, presets: []}; }
  const pill = $('aiPill');
  pill.classList.toggle('ok', !!S.ai.configured); pill.classList.toggle('off', !S.ai.configured);
  $('aiPillText').textContent = S.ai.configured ? `AI 已就绪 · ${S.ai.model}` : '设置 AI';
}

function openSettings(notice) {
  const a = S.ai;
  $('sNotice').hidden = !notice; $('sNotice').textContent = notice || '';
  $('sPreset').innerHTML = (a.presets || []).map((p, i) => `<option value="${i}">${esc(p.name)}</option>`).join('') + '<option value="custom">自定义</option>';
  const idx = (a.presets || []).findIndex(p => p.base === a.base);
  $('sPreset').value = idx >= 0 ? String(idx) : 'custom';
  $('sBase').value = a.base || ''; $('sModel').value = a.model || ''; $('sReason').value = a.reasoning_model || '';
  $('sKey').value = ''; $('sKeyHint').textContent = a.key_hint ? `（已保存：${a.key_hint}）` : '（尚未设置）';
  $('sResult').innerHTML = '';
  $('settings').classList.add('open');
  setTimeout(() => $(a.key_hint ? 'sModel' : 'sKey').focus(), 50);
}

async function saveSettings(test) {
  const body = {base: $('sBase').value.trim(), model: $('sModel').value.trim(), reasoning_model: $('sReason').value.trim()};
  if ($('sKey').value.trim()) body.api_key = $('sKey').value.trim();
  $('sResult').innerHTML = '<span class="hint">正在保存…</span>';
  const d = await postJSON('/api/ai/settings', body).catch(e => ({ok: false, message: String(e)}));
  if (!d.ok) { $('sResult').innerHTML = `<div class="err">${esc(d.message)}</div>`; return; }
  await loadAISettings();
  $('sKey').value = ''; $('sKeyHint').textContent = S.ai.key_hint ? `（已保存：${S.ai.key_hint}）` : '（尚未设置）';
  if (!test) { $('sResult').innerHTML = '<div class="ok">已保存</div>'; return; }
  $('sResult').innerHTML = '<span class="hint">已保存，正在测试连接…</span>';
  const t = await postJSON('/api/ai/test', {}).catch(e => ({ok: false, message: String(e)}));
  $('sResult').innerHTML = t.ok ? `<div class="ok">连接成功：${esc(t.model)} 回复“${esc(t.reply)}”（${t.seconds} 秒）</div>` : `<div class="err">${esc(t.message)}</div>`;
}

function requireAI() {
  if (S.ai.configured) return true;
  openSettings('请先填写 AI 接口（如 DeepSeek API Key），即可使用 AI 解读、讨论与综述功能。');
  return false;
}

/* ------------------------------------------------------------------ stream */

async function streamPost(url, body, onEvent, signal) {
  const r = await fetch(url, {method: 'POST', headers: HEADERS, body: JSON.stringify(body), signal});
  if (!r.ok || !r.body) throw new Error('HTTP ' + r.status);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const {value, done} = await reader.read();
    if (done) break;
    buf += decoder.decode(value, {stream: true});
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of chunk.split('\n')) if (line.startsWith('data: ')) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

/* ------------------------------------------------------------------ reader */

function openReader(opts) {
  Object.assign(R, {text: '', think: '', refs: [], papers: [], note: null, basis: '', model: '', warnings: [], error: ''}, opts);
  $('reader').classList.add('open');
  document.body.style.overflow = 'hidden';
  renderReader(true);
}
function closeReader() {
  if (R.controller) R.controller.abort();
  $('reader').classList.remove('open');
  document.body.style.overflow = '';
}

function renderReader(streaming) {
  $('rKind').textContent = R.kind || TASK_LABEL[R.task] || '';
  $('rTitle').textContent = R.title || '';
  const meta = [];
  if (R.papers.length) meta.push(`文献 ${R.papers.length} 篇`);
  if (R.basis) meta.push(`依据：${R.basis}`);
  if (R.model) meta.push(`模型：${R.model}`);
  if (R.note) meta.push(`已保存到“我的笔记”`);
  $('rMeta').textContent = meta.join(' · ');
  $('rStop').hidden = !streaming;
  for (const id of ['rCopy', 'rDownload', 'rRegen', 'rDiscuss']) $(id).disabled = !!streaming;
  $('rRegen').hidden = !R.task || R.task === 'chat';
  $('rDiscuss').hidden = !R.ids.length;
  $('rStatus').innerHTML = streaming && R.status ? `<span class="spinner"></span>${esc(R.status)}` : '';
  $('rThinkWrap').hidden = !R.think;
  $('rThink').textContent = R.think;
  const body = $('rBody');
  body.innerHTML = R.error ? `<div class="err">${esc(R.error)}</div>` : md(R.text);
  body.classList.toggle('cursor', !!streaming && !!R.text);
  $('rWarn').innerHTML = (R.warnings || []).map(w => `<div class="warn">${esc(w)}</div>`).join('');
  const refs = $('rRefs');
  refs.hidden = !R.refs.length;
  refs.innerHTML = R.refs.length ? '<h3>参考文献（依据引用编号自动生成）</h3>' + R.refs.map(refHTML).join('') : '';
}

function refHTML(r) {
  const who = (r.authors || []).slice(0, 3).join(', ') + ((r.authors || []).length > 3 ? ' et al.' : '');
  const link = r.doi ? `https://doi.org/${r.doi}` : (r.url || '');
  return `<div class="ref" id="ref-${r.n}"><span class="n">[${r.n}]</span><span>${esc(who)} (${esc(r.year || 'n.d.')}). ${esc(r.title)}. <i>${esc(r.journal || '')}</i>
    ${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">${esc(r.doi ? 'doi:' + r.doi : '链接')}</a>` : ''}
    <span class="acts"><button data-interpret="${esc(r.id)}">AI 解读</button><button data-pickref="${esc(r.id)}">加入研读</button></span></span></div>`;
}

function scheduleReader() {
  if (renderTimer) return;
  renderTimer = requestAnimationFrame(() => { renderTimer = null; renderReader(true); });
}

async function runTask(task, ids, question) {
  if (!requireAI()) return;
  if (!ids.length) { toast('请先把文献加入研读清单'); openPanel('basket'); return; }
  const first = S.byId.get(ids[0]);
  const title = task === 'interpret' ? (first ? first.title : '') : `${TASK_LABEL[task]}（${ids.length} 篇文献）${question ? '：' + question.slice(0, 40) : ''}`;
  const controller = new AbortController();
  openReader({task, ids: [...ids], question: question || '', title, kind: TASK_LABEL[task], status: '正在准备…', controller});
  const useFull = task === 'interpret' ? true : $('optFull').checked;
  try {
    await streamPost('/api/ai/run', {task, ids, question, deep: $('optDeep').checked, use_fulltext: useFull}, ev => {
      if (ev.type === 'meta') { if (ev.papers) R.papers = ev.papers; if (ev.basis) R.basis = ev.basis; if (ev.model) R.model = ev.model; }
      else if (ev.type === 'status') R.status = ev.message;
      else if (ev.type === 'reasoning') { R.think += ev.text; R.status = '深度思考中…'; }
      else if (ev.type === 'delta') { R.text += ev.text; R.status = '生成中…'; }
      else if (ev.type === 'done') {
        R.refs = ev.references || []; R.warnings = ev.warnings || []; R.note = ev.note || null;
        if (R.note && R.task === 'review') R.title = R.note.title;
      } else if (ev.type === 'error') R.error = ev.message;
      scheduleReader();
    }, controller.signal);
  } catch (e) {
    if (e.name !== 'AbortError') R.error = '连接中断：' + e.message;
    else R.warnings = [...(R.warnings || []), '已停止生成'];
  }
  R.controller = null;
  cancelAnimationFrame(renderTimer); renderTimer = null;
  renderReader(false);
  if (R.note) { loadNotes(); }
}

async function interpret(id, force) {
  if (!requireAI()) return;
  if (!force) {
    const d = await getJSON('/api/ai/interpretation?id=' + encodeURIComponent(id)).catch(() => null);
    if (d && d.note) { showNote(d.note, d.body); return; }
  }
  runTask('interpret', [id], '');
}

function showNote(note, body) {
  openReader({task: note.kind === 'chat' ? 'chat' : note.kind, ids: note.paper_ids || [], question: note.question || '', title: note.title, kind: TASK_LABEL[note.kind] || note.kind, status: '', controller: null});
  R.text = body; R.refs = note.references || []; R.note = note; R.basis = note.basis || ''; R.model = note.model || '';
  R.papers = (note.paper_ids || []).map((id, i) => ({n: i + 1, id}));
  renderReader(false);
}

function downloadText(name, text) {
  const blob = new Blob([text], {type: 'text/markdown;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function readerMarkdown() {
  const refs = R.refs.map(r => `[${r.n}] ${(r.authors || []).slice(0, 3).join(', ')}${(r.authors || []).length > 3 ? ' et al.' : ''} (${r.year || 'n.d.'}). ${r.title}. ${r.journal || ''}${r.doi ? ' https://doi.org/' + r.doi : ''}`);
  return `# ${R.title}\n\n${R.text.trim()}\n` + (refs.length ? `\n## 参考文献\n\n${refs.join('  \n')}\n` : '');
}

/* -------------------------------------------------------------------- chat */

function chatContextFromBasket() {
  const ids = [...C.contextIds];
  for (const id of S.basket) if (!ids.includes(id)) ids.push(id);
  return ids;
}

function renderChat() {
  const log = $('chatLog');
  $('chatScope').value = C.scope;
  if (!C.messages.length) {
    const tips = SUGGESTIONS[C.scope] || [];
    const scopeTip = {
      selection: `AI 将依据研读清单中的 ${S.basket.length} 篇文献回答${S.basket.length ? '' : '（清单为空时，请先加入文献或切换到“整个文献库”）'}。`,
      library: `每次提问时，AI 会先从本地 ${S.papers.length} 篇文献中检索最相关的论文，再据此回答并标注出处。`,
      filtered: `AI 会在当前筛选结果（${S.view.length} 篇）中检索相关论文再回答。`,
    }[C.scope];
    log.innerHTML = `<div class="chat-empty">${esc(scopeTip)}<div class="suggest">${tips.map(t => `<button data-suggest="${esc(t)}">${esc(t)}</button>`).join('')}</div></div>`;
  } else {
    log.innerHTML = C.messages.map((m, i) => {
      if (m.role === 'user') return `<div class="msg user">${esc(m.content)}</div>`;
      const refs = (m.refs || []).map(r => `<span class="refchip" data-chatref="${i}:${r.n}" title="${esc(r.title)}">[${r.n}] ${esc((r.title || '').slice(0, 42))}</span>`).join('');
      const think = m.think ? `<details class="think"><summary>思考过程</summary><div>${esc(m.think)}</div></details>` : '';
      const status = m.pending && m.status ? `<div class="status"><span class="spinner" style="display:inline-block;vertical-align:-2px;margin-right:6px"></span>${esc(m.status)}</div>` : '';
      const body = m.error ? `<div class="err">${esc(m.error)}</div>` : `<div class="md${m.pending ? ' cursor' : ''}" data-msg="${i}">${md(m.content)}</div>`;
      const warns = (m.warnings || []).map(w => `<div class="warn">${esc(w)}</div>`).join('');
      return `<div class="msg ai">${think}${status}${body}${warns}${refs ? `<div class="refs-mini">${refs}</div>` : ''}</div>`;
    }).join('');
    log.scrollTop = log.scrollHeight;
  }
  const ctxIds = C.contextIds;
  $('chatCtx').hidden = !ctxIds.length;
  $('chatCtxSum').textContent = `本次讨论参考了 ${ctxIds.length} 篇文献`;
  $('chatCtxList').innerHTML = ctxIds.map(id => { const p = S.byId.get(id); return `<li><a data-open="${esc(id)}">${esc(p ? p.title : id)}</a></li>`; }).join('');
  $('chatStop').hidden = !C.busy; $('chatSend').disabled = C.busy;
}

async function sendChat(text) {
  text = (text || '').trim();
  if (!text || C.busy) return;
  if (!requireAI()) return;
  if (C.scope === 'selection' && !S.basket.length && !C.contextIds.length) {
    toast('研读清单为空：请先加入文献，或把讨论范围切换为“整个文献库”');
    return;
  }
  C.messages.push({role: 'user', content: text});
  const msg = {role: 'assistant', content: '', refs: [], think: '', pending: true, status: '正在准备…'};
  C.messages.push(msg);
  C.busy = true; C.controller = new AbortController();
  $('chatInput').value = '';
  renderChat();
  const history = C.messages.slice(0, -1).filter(m => !m.error).map(m => ({role: m.role, content: m.content}));
  const body = {messages: history, scope: C.scope, deep: $('chatDeep').checked, use_fulltext: $('optFull').checked,
    context_ids: C.scope === 'selection' ? chatContextFromBasket() : C.contextIds};
  if (C.scope === 'filtered') body.filter_ids = S.view.map(p => p.id);
  let frame = null;
  const redraw = () => { if (!frame) frame = requestAnimationFrame(() => { frame = null; renderChat(); }); };
  try {
    await streamPost('/api/ai/chat', body, ev => {
      if (ev.type === 'meta') { if (ev.context_ids) C.contextIds = ev.context_ids; if (ev.papers) { C.papers = ev.papers; msg.papers = ev.papers; } }
      else if (ev.type === 'status') msg.status = ev.message;
      else if (ev.type === 'reasoning') { msg.think += ev.text; msg.status = '深度思考中…'; }
      else if (ev.type === 'delta') { msg.content += ev.text; msg.status = ''; }
      else if (ev.type === 'done') { msg.refs = ev.references || []; msg.warnings = ev.warnings || []; }
      else if (ev.type === 'error') msg.error = ev.message;
      redraw();
    }, C.controller.signal);
  } catch (e) {
    if (e.name === 'AbortError') msg.warnings = ['已停止生成'];
    else msg.error = '连接中断：' + e.message;
  }
  msg.pending = false; C.busy = false; C.controller = null;
  cancelAnimationFrame(frame);
  renderChat();
}

function newChat() {
  if (C.controller) C.controller.abort();
  Object.assign(C, {messages: [], contextIds: [], papers: [], busy: false, controller: null});
  renderChat();
}

async function saveChat() {
  if (!C.messages.length) { toast('当前没有对话内容'); return; }
  const firstQ = (C.messages.find(m => m.role === 'user') || {}).content || 'AI 讨论';
  const d = await postJSON('/api/ai/chat-save', {title: 'AI 讨论：' + firstQ.slice(0, 50), messages: C.messages.filter(m => !m.error).map(m => ({role: m.role, content: m.content})), context_ids: C.contextIds});
  toast(d.ok ? '对话已保存到“我的笔记”' : (d.message || '保存失败'));
  loadNotes();
}

function discussPapers(ids, seed) {
  newChat();
  C.scope = 'selection'; store.set('chatScope', C.scope);
  C.contextIds = [...ids];
  if (seed) C.messages.push(...seed);
  openPanel('chat');
  renderChat();
}

/* ------------------------------------------------------------------- notes */

async function loadNotes() {
  const d = await getJSON('/api/ai/notes').catch(() => ({notes: []}));
  S.notes = d.notes || [];
  S.notedIds = new Set(S.notes.filter(n => n.kind === 'interpret').flatMap(n => n.paper_ids || []));
  $('notesCount').textContent = S.notes.length;
  $('notesList').innerHTML = S.notes.length ? S.notes.map(n => `<div class="note" data-note="${esc(n.id)}">
      <span class="k">${esc(TASK_LABEL[n.kind] || n.kind)}</span>
      <div class="body"><div class="title">${esc(n.title)}</div><div class="when">${esc((n.created || '').replace('T', ' ').slice(0, 16))}${n.paper_ids && n.paper_ids.length ? ' · ' + n.paper_ids.length + ' 篇文献' : ''}</div></div>
      <button class="del" data-delnote="${esc(n.id)}" title="删除">×</button></div>`).join('')
    : '<div class="basket-empty">还没有笔记<br>AI 解读、总结与综述会自动保存在这里。</div>';
}

async function openNote(id) {
  const d = await getJSON('/api/ai/note?id=' + encodeURIComponent(id)).catch(() => null);
  if (d && d.note) showNote(d.note, d.body); else toast('笔记不存在或已删除');
}

/* ----------------------------------------------------------------- popover */

function showCitation(anchor, ns, lookup) {
  const pop = $('popover');
  const items = ns.map(n => {
    const ref = lookup(n);
    if (!ref || !ref.id) return `<div class="p-item"><div class="p-title">[${n}] 该编号不在提供的文献材料中</div></div>`;
    const p = S.byId.get(ref.id) || ref;
    const link = p.doi ? `https://doi.org/${p.doi}` : (p.url || '');
    return `<div class="p-item"><div class="p-title">[${n}] ${esc(p.title)}</div>
      <div class="p-meta">${esc(authorsShort(p))} · ${esc(p.journal || '')} · ${esc(p.year || '')}</div>
      <div class="p-acts">${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">原文</a>` : ''}<button data-interpret="${esc(ref.id)}">AI 解读</button><button data-pickref="${esc(ref.id)}">加入研读</button><button data-open="${esc(ref.id)}">在列表中查看</button></div></div>`;
  }).join('');
  pop.innerHTML = items;
  pop.classList.add('open');
  const rect = anchor.getBoundingClientRect();
  const w = pop.offsetWidth, h = pop.offsetHeight;
  let left = Math.min(Math.max(12, rect.left - 20), window.innerWidth - w - 12);
  let top = rect.bottom + 8;
  if (top + h > window.innerHeight - 12) top = Math.max(12, rect.top - h - 8);
  pop.style.left = left + 'px'; pop.style.top = top + 'px';
}
function hidePopover() { $('popover').classList.remove('open'); }

function readerLookup(n) {
  return R.refs.find(r => r.n === n) || R.papers.find(p => p.n === n) || null;
}

function locatePaper(id) {
  const p = S.byId.get(id);
  if (!p) return;
  closeReader(); hidePopover();
  S.f = defaultFilters(); $('q').value = p.title.slice(0, 60);
  S.f.q = p.title.slice(0, 60);
  for (const k of ['onlyNew', 'onlyPre', 'onlyCur', 'onlyAbs', 'onlyPicked']) $(k).checked = false;
  S.page = 1; renderFacets(); apply();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

/* ------------------------------------------------------------- translation */

function setShowZh(on) { S.showZh = on; $('showZh').checked = on; store.set('showZh', on); render(); }

async function translateOne(id, button) {
  if (!requireAI()) return;
  button.disabled = true; button.textContent = '翻译中…';
  const d = await postJSON('/api/translate', {id}).catch(e => ({ok: false, message: String(e)}));
  if (!d.ok) { setStatus({status: 'error', message: d.message}); button.disabled = false; button.textContent = '中文翻译'; return; }
  const p = S.byId.get(id);
  if (p) Object.assign(p, {title_zh: d.translation.title_zh, abstract_zh: d.translation.abstract_zh, zh_needs_review: d.translation.needs_review && !d.translation.reviewed, zh_issues: d.translation.issues || []});
  toast(d.translation.needs_review ? '翻译完成（自动检查发现问题，已标记“译文待校对”）' : '翻译完成');
  setShowZh(true);
}

/* ------------------------------------------------------------------ status */

function setStatus(d) {
  const running = d.status === 'running';
  const visible = running || d.status === 'error' || (d.status === 'done' && d.message && !setStatus.dismissed);
  $('statusbar').hidden = !visible;
  $('dot').className = 'dot ' + (d.status || 'idle');
  $('msg').textContent = d.message || '';
  $('log').textContent = (d.log || []).join('\n');
  $('log').scrollTop = $('log').scrollHeight;
  document.querySelectorAll('[data-act]').forEach(b => { b.disabled = running; });
}

async function runAction(url) {
  $('moreMenu').classList.remove('open');
  if (url === '/api/send-email' && !confirm('确定向所有已配置的收件人发送最近一次更新的邮件摘要吗？')) return;
  const r = await fetch(url, {method: 'POST', headers: {'X-Requested-With': '3DGenomeHub'}});
  const d = await r.json();
  setStatus.dismissed = false;
  setStatus({status: d.ok ? 'running' : 'error', message: d.message});
  if (d.ok && !poll) poll = setInterval(checkStatus, 1500);
}

async function checkStatus() {
  const d = await getJSON('/api/status').catch(() => null);
  if (!d) return;
  if (d.status === 'idle') { $('statusbar').hidden = true; return; }
  setStatus(d);
  if (d.status === 'running' && !poll) poll = setInterval(checkStatus, 1500);
  else if (d.status !== 'running' && poll) { clearInterval(poll); poll = null; loadAll(); }
}

/* ------------------------------------------------------------------ events */

document.addEventListener('click', e => {
  const t = e.target.closest('[data-track],[data-cat],[data-method],[data-page],[data-act],[data-tr],[data-trtoggle],[data-interpret],[data-discuss],[data-unpick],[data-open],[data-pickref],[data-task],[data-tab],[data-note],[data-delnote],[data-suggest],[data-chatref],.cite,.abs');
  if (!t) { if (!e.target.closest('#popover')) hidePopover(); if (!e.target.closest('#moreMenu')) $('moreMenu').classList.remove('open'); return; }
  if (!t.closest('#popover') && !t.classList.contains('cite') && !t.dataset.chatref) hidePopover();
  if (t.classList.contains('cite')) {
    e.preventDefault();
    const ns = (t.dataset.ns || '').split(',').map(Number).filter(Boolean);
    const msgEl = t.closest('[data-msg]');
    if (msgEl) {
      const m = C.messages[+msgEl.dataset.msg] || {};
      const papers = m.papers || C.papers;
      showCitation(t, ns, n => (m.refs || []).find(r => r.n === n) || papers.find(p => p.n === n));
    } else showCitation(t, ns, readerLookup);
    return;
  }
  if (t.dataset.chatref) {
    const [i, n] = t.dataset.chatref.split(':').map(Number);
    const m = C.messages[i] || {};
    showCitation(t, [n], k => (m.refs || []).find(r => r.n === k));
    return;
  }
  if (t.dataset.interpret) { hidePopover(); interpret(t.dataset.interpret); return; }
  if (t.dataset.discuss) { discussPapers([t.dataset.discuss]); return; }
  if (t.dataset.tr) { translateOne(t.dataset.tr, t); return; }
  if (t.dataset.trtoggle) { setShowZh(true); return; }
  if (t.dataset.unpick) { toggleBasket(t.dataset.unpick, false); return; }
  if (t.dataset.pickref) { hidePopover(); toggleBasket(t.dataset.pickref, true); toast('已加入研读清单'); return; }
  if (t.dataset.open) { locatePaper(t.dataset.open); return; }
  if (t.dataset.tab) { setTab(t.dataset.tab); return; }
  if (t.dataset.note) { openNote(t.dataset.note); return; }
  if (t.dataset.delnote) {
    if (confirm('确定删除这条笔记吗？')) postJSON('/api/ai/note-delete', {id: t.dataset.delnote}).then(loadNotes);
    return;
  }
  if (t.dataset.suggest) { sendChat(t.dataset.suggest); return; }
  if (t.dataset.task) {
    const task = t.dataset.task, question = $('taskFocus').value.trim();
    if (task === 'discuss') {
      if (!S.basket.length) { toast('请先把文献加入研读清单'); return; }
      discussPapers(S.basket);
      if (question) sendChat(question);
      return;
    }
    if (task === 'ask' && !question) { toast('请先在“研究焦点 / 问题”中输入问题'); $('taskFocus').focus(); return; }
    runTask(task, S.basket, question);
    return;
  }
  if (t.classList.contains('abs')) { t.classList.toggle('open'); return; }
  if (t.dataset.act) { runAction(t.dataset.act); return; }
  if (t.dataset.page) { S.page = +t.dataset.page; render(); window.scrollTo({top: 0, behavior: 'smooth'}); return; }
  if ('track' in t.dataset) return setFilter('track', t.dataset.track);
  if (t.dataset.cat) return setFilter('cat', t.dataset.cat);
  if (t.dataset.method) return setFilter('method', t.dataset.method);
});

document.addEventListener('change', e => {
  if (e.target.dataset.pick) toggleBasket(e.target.dataset.pick, e.target.checked);
});

let qTimer = null;
$('q').addEventListener('input', e => { clearTimeout(qTimer); qTimer = setTimeout(() => { S.f.q = e.target.value.trim(); S.page = 1; apply(); }, 180); });
$('sort').addEventListener('change', e => { S.sort = e.target.value; apply(); });
$('source').addEventListener('change', e => { S.f.source = e.target.value; S.page = 1; apply(); });
$('yFrom').addEventListener('change', e => { S.f.yFrom = +e.target.value || 0; S.page = 1; apply(); });
$('yTo').addEventListener('change', e => { S.f.yTo = +e.target.value || 9999; S.page = 1; apply(); });
for (const id of ['onlyNew', 'onlyPre', 'onlyCur', 'onlyAbs', 'onlyPicked']) $(id).addEventListener('change', e => { S.f[id] = e.target.checked; S.page = 1; apply(); });
$('reset').addEventListener('click', () => {
  S.f = defaultFilters(); $('q').value = '';
  for (const id of ['onlyNew', 'onlyPre', 'onlyCur', 'onlyAbs', 'onlyPicked']) $(id).checked = false;
  $('yFrom').value = ''; $('yTo').value = ''; S.page = 1; renderFacets(); apply();
});
$('showZh').checked = S.showZh;
$('showZh').addEventListener('change', e => setShowZh(e.target.checked));
$('btnTrPage').addEventListener('click', async () => {
  if (!requireAI()) return;
  const ids = S.view.slice((S.page - 1) * PER_PAGE, S.page * PER_PAGE).filter(p => !p.title_zh).map(p => p.id);
  if (!ids.length) { setShowZh(true); toast('本页论文均已有中文译文'); return; }
  const d = await postJSON('/api/translate-batch', {ids});
  setStatus.dismissed = false;
  setStatus({status: d.ok ? 'running' : 'error', message: d.message});
  if (d.ok) { S.showZh = true; $('showZh').checked = true; store.set('showZh', true); if (!poll) poll = setInterval(checkStatus, 1500); }
});
$('btnPickPage').addEventListener('click', () => addToBasket(pageIds()));
$('addTop').addEventListener('click', () => addToBasket(S.view.slice(0, 20).map(p => p.id)));
$('clearBasket').addEventListener('click', () => { if (S.basket.length && confirm('清空研读清单？')) { S.basket = []; saveBasket(); render(); } });
$('logBtn').addEventListener('click', () => { const l = $('log'); l.style.display = l.style.display === 'block' ? 'none' : 'block'; });
$('hideStatus').addEventListener('click', () => { setStatus.dismissed = true; $('statusbar').hidden = true; $('log').style.display = 'none'; });
$('moreBtn').addEventListener('click', e => { e.stopPropagation(); $('moreMenu').classList.toggle('open'); });
$('menuSettings').addEventListener('click', () => { $('moreMenu').classList.remove('open'); openSettings(); });
$('aiPill').addEventListener('click', () => openSettings());
$('filtersToggle').addEventListener('click', () => $('filters').classList.toggle('open'));
$('fab').addEventListener('click', () => openPanel());
$('closeDrawer').addEventListener('click', () => $('aiPanel').classList.remove('open'));

$('sPreset').addEventListener('change', e => {
  const p = (S.ai.presets || [])[+e.target.value];
  if (!p) return;
  $('sBase').value = p.base; $('sModel').value = p.model; $('sReason').value = p.reasoning_model;
});
$('sSave').addEventListener('click', () => saveSettings(true));
$('sSaveOnly').addEventListener('click', () => saveSettings(false));
$('sClose').addEventListener('click', () => $('settings').classList.remove('open'));
$('settings').addEventListener('click', e => { if (e.target.id === 'settings') $('settings').classList.remove('open'); });

$('rClose').addEventListener('click', closeReader);
$('reader').addEventListener('click', e => { if (e.target.id === 'reader') closeReader(); });
$('rStop').addEventListener('click', () => { if (R.controller) R.controller.abort(); });
$('rCopy').addEventListener('click', async () => { try { await navigator.clipboard.writeText(readerMarkdown()); toast('已复制 Markdown'); } catch (e) { toast('复制失败，请手动选择文本'); } });
$('rDownload').addEventListener('click', () => {
  if (R.note) { window.location.href = '/api/ai/note-download?id=' + encodeURIComponent(R.note.id); return; }
  downloadText((R.title || 'ai-note').slice(0, 60).replace(/[\\/:*?"<>|]+/g, '_') + '.md', readerMarkdown());
});
$('rRegen').addEventListener('click', () => { if (R.task === 'interpret') interpret(R.ids[0], true); else runTask(R.task, R.ids, R.question); });
$('rDiscuss').addEventListener('click', () => {
  const seed = R.text ? [{role: 'user', content: `请${R.kind || 'AI 解读'}${R.question ? '：' + R.question : ''}`}, {role: 'assistant', content: R.text, refs: R.refs, papers: R.papers}] : null;
  const ids = R.ids;
  closeReader();
  discussPapers(ids, seed);
});

$('chatScope').addEventListener('change', e => {
  C.scope = e.target.value; store.set('chatScope', C.scope);
  if (C.messages.length) newChat(); else renderChat();
});
$('chatNew').addEventListener('click', newChat);
$('chatSave').addEventListener('click', saveChat);
$('chatStop').addEventListener('click', () => { if (C.controller) C.controller.abort(); });
$('chatForm').addEventListener('submit', e => { e.preventDefault(); sendChat($('chatInput').value); });
$('chatInput').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendChat($('chatInput').value); } });
$('optDeep').checked = store.get('deep', false);
$('optFull').checked = store.get('full', true);
$('chatDeep').checked = store.get('deep', false);
$('optDeep').addEventListener('change', e => { store.set('deep', e.target.checked); $('chatDeep').checked = e.target.checked; });
$('chatDeep').addEventListener('change', e => { store.set('deep', e.target.checked); $('optDeep').checked = e.target.checked; });
$('optFull').addEventListener('change', e => store.set('full', e.target.checked));

document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if ($('popover').classList.contains('open')) return hidePopover();
  if ($('settings').classList.contains('open')) return $('settings').classList.remove('open');
  if ($('reader').classList.contains('open')) return closeReader();
  $('aiPanel').classList.remove('open');
});
window.addEventListener('scroll', hidePopover, {passive: true});

loadAISettings();
loadNotes().then(() => render());
loadAll().catch(e => { $('list').innerHTML = `<div class="empty">加载文献失败：${esc(e)}</div>`; });
checkStatus();
