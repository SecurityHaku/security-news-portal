/* Security News Portal — フロントエンド（フレームワーク不使用）
   data/news.json を読み込み、ダッシュボードを描画する。 */
'use strict';

const CATEGORIES = {
  'vulnerability':  { label: '脆弱性',              color: 'var(--c-vulnerability)' },
  'ransomware':     { label: 'ランサムウェア',       color: 'var(--c-ransomware)' },
  'apt':            { label: 'APT・脅威アクター',    color: 'var(--c-apt)' },
  'data-breach':    { label: 'データ漏洩',           color: 'var(--c-data-breach)' },
  'cloud-oss':      { label: 'クラウド・OSS',        color: 'var(--c-cloud-oss)' },
  'ai':             { label: 'AI・LLMセキュリティ',  color: 'var(--c-ai)' },
  'regulation':     { label: '規制・コンプライアンス', color: 'var(--c-regulation)' },
  'tools-research': { label: 'ツール・リサーチ',      color: 'var(--c-tools-research)' },
};

// 最終更新などの絶対時刻は日本時間(JST)で表示する
const fmtJST = (iso) => {
  try {
    return new Date(iso).toLocaleString('ja-JP', {
      timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    }) + ' JST';
  } catch { return iso; }
};

const state = {
  all: [],
  category: 'all',      // 'all' or category key
  period: 'current',    // 'current' | '3m' | 'all'
  query: '',
  sort: 'date',
};

// 日本語版があれば優先（enrich.py が付与。無ければ原文）
const titleOf = (it) => it.title_ja || it.title;
const summaryOf = (it) => it.summary_ja || it.summary || '';

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function relTime(iso) {
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  const day = 86400;
  if (diff < day) return '今日';
  if (diff < 2 * day) return '昨日';
  if (diff < 7 * day) return `${Math.floor(diff / day)}日前`;
  return d.toLocaleDateString('ja-JP', { month: 'numeric', day: 'numeric' });
}

function monthKey(iso) { return iso.slice(0, 7); }
function latestMonth() {
  return state.all.reduce((m, it) => {
    const k = monthKey(it.published);
    return k > m ? k : m;
  }, '0000-00');
}

/* ---- フィルタ適用 ---- */
function periodItems() {
  if (state.period === 'all') return state.all;
  if (state.period === 'current') {
    const lm = latestMonth();
    return state.all.filter((it) => monthKey(it.published) === lm);
  }
  // 3m: 最新月から2か月前まで
  const lm = latestMonth();
  const [y, m] = lm.split('-').map(Number);
  const from = new Date(Date.UTC(y, m - 3, 1)); // 3か月分
  return state.all.filter((it) => new Date(it.published) >= from);
}

function filtered() {
  let items = periodItems();
  if (state.category !== 'all') items = items.filter((it) => it.category === state.category);
  if (state.query) {
    const q = state.query.toLowerCase();
    items = items.filter((it) =>
      (it.title + ' ' + (it.title_ja || '') + ' ' + (it.summary || '') + ' ' +
       (it.summary_ja || '') + ' ' + (it.analysis_ja || '') + ' ' + it.source + ' ' +
       (it.cves || []).join(' ')).toLowerCase().includes(q));
  }
  items = items.slice().sort((a, b) =>
    state.sort === 'score'
      ? (b.score || 0) - (a.score || 0)
      : new Date(b.published) - new Date(a.published));
  return items;
}

/* ---- 描画 ---- */
function renderKpi() {
  const items = periodItems();
  const lm = latestMonth();
  const catCount = new Set(items.map((it) => it.category)).size;
  const topSource = Object.entries(
    items.reduce((acc, it) => ((acc[it.source] = (acc[it.source] || 0) + 1), acc), {})
  ).sort((a, b) => b[1] - a[1])[0];
  const withCve = items.filter((it) => (it.cves || []).length).length;

  const periodLabel = state.period === 'all' ? '全期間'
    : state.period === '3m' ? '直近3か月' : `${lm.replace('-', '年')}月`;

  const kpis = [
    { label: `対象件数 (${periodLabel})`, value: items.length, sub: '表示中のニュース' },
    { label: '追跡カテゴリ', value: catCount, sub: `全${Object.keys(CATEGORIES).length}カテゴリ中` },
    { label: 'CVE言及', value: withCve, sub: '脆弱性IDを含む記事' },
    { label: '最多ソース', value: topSource ? topSource[1] : 0, sub: topSource ? topSource[0] : '—' },
  ];
  const row = $('#kpiRow');
  row.innerHTML = '';
  kpis.forEach((k) => {
    row.appendChild(el('div', 'kpi',
      `<div class="k-label">${esc(k.label)}</div>
       <div class="k-value">${k.value}</div>
       <div class="k-sub">${esc(k.sub)}</div>`));
  });
}

function chip(cat) {
  const c = CATEGORIES[cat] || { label: cat, color: 'var(--muted)' };
  return `<span class="chip" style="background:${c.color}">${esc(c.label)}</span>`;
}

function renderCategoryNav() {
  const items = periodItems();
  const counts = items.reduce((acc, it) => ((acc[it.category] = (acc[it.category] || 0) + 1), acc), {});
  const list = $('#categoryList');
  list.innerHTML = '';

  const mk = (key, label, color, n) => {
    const li = el('li');
    const btn = el('button', key === state.category ? 'active' : '',
      `<span class="dot" style="background:${color || 'var(--accent)'}"></span>
       <span class="label">${esc(label)}</span><span class="n">${n}</span>`);
    btn.addEventListener('click', () => { state.category = key; renderAll(); });
    li.appendChild(btn);
    return li;
  };
  list.appendChild(mk('all', 'すべて', 'var(--accent)', items.length));
  Object.entries(CATEGORIES).forEach(([key, c]) =>
    list.appendChild(mk(key, c.label, c.color, counts[key] || 0)));
}

function renderRank() {
  const lm = latestMonth();
  const monthItems = state.all.filter((it) => monthKey(it.published) === lm);
  // 各カテゴリで注目度1位（score.py の featured）。無ければスコア上位で代替。
  let top = monthItems.filter((it) => it.featured)
    .sort((a, b) => (b.score || 0) - (a.score || 0));
  if (!top.length) {
    top = monthItems.slice().sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 8);
  }
  $('#rankScope').textContent = top.length ? `（${lm.replace('-', '年')}月）` : '';
  const strip = $('#rankStrip');
  strip.innerHTML = '';
  if (!top.length) { strip.appendChild(el('p', 'empty', 'データがありません。')); return; }
  top.forEach((it, i) => {
    strip.appendChild(el('a', 'rank-card',
      `<span class="num">${i + 1}</span>
       ${chip(it.category)}
       <h3>${esc(titleOf(it))}</h3>
       <div class="meta">${esc(it.source)} ・ ${relTime(it.published)}</div>`))
      .setAttribute('href', it.url);
    strip.lastChild.target = '_blank';
    strip.lastChild.rel = 'noopener';
  });
}

function renderGrid() {
  const items = filtered();
  const maxScore = Math.max(1, ...state.all.map((it) => it.score || 0));
  $('#resultMeta').textContent = `${items.length} 件を表示`;
  const grid = $('#newsGrid');
  grid.innerHTML = '';
  $('#emptyState').classList.toggle('hidden', items.length > 0);

  items.forEach((it) => {
    const cves = (it.cves || []).slice(0, 4)
      .map((c) => `<span class="cve">${esc(c)}</span>`).join('');
    const orig = it.title_ja ? `<div class="orig">原題: ${esc(it.title)}</div>` : '';
    const aLabel = it.enriched_by === 'llm' ? 'アナリスト見解' : '着眼点（自動生成）';
    const analysis = it.analysis_ja
      ? `<details class="analysis"><summary>${aLabel}</summary><p>${esc(it.analysis_ja)}</p></details>`
      : '';
    const card = el('article', 'card',
      `<div class="card-top">${chip(it.category)}
        <span>${relTime(it.published)}</span></div>
       <h3><a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(titleOf(it))}</a></h3>
       ${orig}
       <p class="summary">${esc(summaryOf(it))}</p>
       ${cves ? `<div class="cves">${cves}</div>` : ''}
       ${analysis}
       <div class="score-meter" style="--v:${Math.round(100 * (it.score || 0) / maxScore)}"><i></i></div>
       <div class="card-foot"><span>${esc(it.source)}</span>
         <span>注目度 ${(it.score || 0).toFixed(1)}</span></div>`);
    grid.appendChild(card);
  });
}

function renderAll() {
  renderKpi();
  renderCategoryNav();
  renderRank();
  renderGrid();
}

/* ---- レポートモーダル ---- */
async function openReportModal() {
  const modal = $('#reportModal');
  const list = $('#reportList');
  list.innerHTML = '<li>読み込み中…</li>';
  modal.classList.remove('hidden');
  try {
    const res = await fetch('reports/index.json', { cache: 'no-store' });
    if (!res.ok) throw new Error();
    const reports = await res.json();
    list.innerHTML = '';
    if (!reports.length) { list.innerHTML = '<li>まだレポートがありません。</li>'; return; }
    reports.forEach((r) => {
      const isPdf = /\.pdf$/i.test(r.file);
      const link = isPdf
        ? `<a class="btn" href="reports/${esc(r.file)}" download>PDF</a>`
        : `<a class="btn" href="reports/${esc(r.file)}" target="_blank" rel="noopener">HTMLで開く</a>`;
      const li = el('li', '', `
        <span>${esc(r.month_label)}<br><span class="r-meta">全${r.total}件 / 上位${r.top_n}件</span></span>
        ${link}`);
      list.appendChild(li);
    });
  } catch {
    list.innerHTML =
      '<li>レポート一覧を取得できませんでした。<code>generate_report.py</code> を実行してください。</li>';
  }
}

/* ---- 初期化 ---- */
function wireEvents() {
  $('#themeBtn').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('snp-theme', next); } catch {}
  });
  try {
    const saved = localStorage.getItem('snp-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
  } catch {}

  $('#periodSeg').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    state.period = b.dataset.period;
    [...e.currentTarget.children].forEach((c) => c.classList.toggle('active', c === b));
    renderAll();
  });

  let t;
  $('#searchInput').addEventListener('input', (e) => {
    clearTimeout(t);
    t = setTimeout(() => { state.query = e.target.value.trim(); renderGrid(); }, 150);
  });
  $('#sortSelect').addEventListener('change', (e) => { state.sort = e.target.value; renderGrid(); });

  $('#reportBtn').addEventListener('click', openReportModal);
  $('#reportClose').addEventListener('click', () => $('#reportModal').classList.add('hidden'));
  $('#reportModal').addEventListener('click', (e) => {
    if (e.target.id === 'reportModal') e.target.classList.add('hidden');
  });
  $('#printBtn').addEventListener('click', () => { $('#reportModal').classList.add('hidden'); window.print(); });

  $('#refreshBtn').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = '⏳ 更新中…';
    const ok = await loadData();
    if (ok) renderAll();
    btn.textContent = ok ? '✓ 更新しました' : '⚠ 取得失敗';
    setTimeout(() => { btn.textContent = label; btn.disabled = false; }, 1600);
  });
}

// news.json + meta.json を読み込み、state と「最終更新」表示を更新する。
async function loadData() {
  const bust = `?t=${Date.now()}`;
  let data;
  try {
    data = await (await fetch('data/news.json' + bust, { cache: 'no-store' })).json();
  } catch {
    $('#updatedAt').textContent = 'データを読み込めませんでした';
    return false;
  }
  if (!Array.isArray(data) || !data.length) {
    $('#updatedAt').textContent = 'ニュースがありません';
    return false;
  }
  state.all = data;

  let updatedText = '';
  try {
    const meta = await (await fetch('data/meta.json' + bust, { cache: 'no-store' })).json();
    if (meta && meta.updated_at) updatedText = `最終更新: ${fmtJST(meta.updated_at)}`;
  } catch { /* meta.json 未生成 */ }
  if (!updatedText) {
    const newest = state.all.reduce((a, b) => (a.published > b.published ? a : b));
    updatedText = `最終更新: ${fmtJST(newest.published)}`;
  }
  $('#updatedAt').textContent = `${updatedText} ・ ${state.all.length} 記事`;
  $('#seedBanner').classList.toggle('hidden', !state.all.every((it) => it.seed));
  return true;
}

async function init() {
  wireEvents();
  if (await loadData()) renderAll();
}

init();
