// 전역 상태
const state = {
  query: "",
  results: [],
  expanded: false,
  basicTotal: 0,
  selectedSlug: null,
  pageData: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {
  meta: $("#meta"),
  viewEmpty: $("#view-empty"),
  viewResults: $("#view-results"),
  viewEmptyResults: $("#view-empty-results"),
  searchForm: $("#search-form"),
  searchInput: $("#search-input"),
  searchForm2: $("#search-form-2"),
  searchInput2: $("#search-input-2"),
  resultsMeta: $("#results-meta"),
  resultsList: $("#results-list"),
  pageView: $("#page-view"),
  emptyTitle: $("#empty-title"),
  emptySub: $("#empty-sub"),
  aiCtaLarge: $("#ai-cta-large"),
};

// --- 초기 로드 ---
async function init() {
  // 메타 정보
  try {
    const r = await fetch("/api/index");
    const data = await r.json();
    els.meta.textContent = `${data.total_pages} pages · ${data.total_links} links`;
  } catch (e) {
    els.meta.textContent = "오프라인";
  }

  // suggestion 버튼
  $$(".suggestion").forEach(b => {
    b.addEventListener("click", () => {
      const q = b.dataset.q || "";
      els.searchInput.value = q;
      doSearch(q);
    });
  });

  // 검색 폼
  els.searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    doSearch(els.searchInput.value);
  });
  els.searchForm2.addEventListener("submit", (e) => {
    e.preventDefault();
    doSearch(els.searchInput2.value);
  });

  // empty state AI CTA
  els.aiCtaLarge.addEventListener("click", () => callAI(state.query, []));

  // hashchange 처리 (Task 11에서 페이지 로드)
  window.addEventListener("hashchange", handleHash);
  handleHash();
}

// --- 검색 ---
async function doSearch(query) {
  query = (query || "").trim();
  state.query = query;
  if (!query) {
    showEmpty();
    return;
  }
  const r = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
  const data = await r.json();
  state.results = data.results;
  state.expanded = data.expanded || false;
  state.basicTotal = data.basic_total || data.total;

  // URL hash 갱신
  setHash({ q: query, page: null });

  if (data.total === 0) {
    showEmptyResults(query);
  } else {
    showResults();
  }
}

function showEmpty() {
  els.viewEmpty.classList.remove("hidden");
  els.viewResults.classList.add("hidden");
  els.viewEmptyResults.classList.add("hidden");
}

function showResults() {
  els.viewEmpty.classList.add("hidden");
  els.viewResults.classList.remove("hidden");
  els.viewEmptyResults.classList.add("hidden");
  els.searchInput2.value = state.query;

  const metaText = state.expanded
    ? `${state.results.length}개 (본문 grep까지 확장)`
    : `${state.results.length}개 매칭`;
  els.resultsMeta.textContent = metaText;

  renderResultList();

  // 첫 카드 자동 선택
  if (state.results.length > 0) {
    selectPage(state.results[0].slug);
  }
}

function showEmptyResults(query) {
  els.viewEmpty.classList.add("hidden");
  els.viewResults.classList.add("hidden");
  els.viewEmptyResults.classList.remove("hidden");
  els.emptyTitle.textContent = "wiki에 직접 매칭되는 페이지가 없어요";
  els.emptySub.textContent = `"${query}" — AI가 wiki 전체에서 관련 페이지를 찾아 답변할 수 있어요.`;
}

function renderResultList() {
  const html = [];
  if (state.expanded) {
    html.push(`<div class="expansion-notice">🔍 결과가 적어 본문까지 자동 검색 — ${state.results.length - state.basicTotal}개 추가</div>`);
  }
  for (const r of state.results) {
    const isActive = r.slug === state.selectedSlug ? "active" : "";
    const snippet = r.snippet
      ? `<div class="result-card-snippet">${highlight(r.snippet, state.query)}</div>`
      : "";
    html.push(`
      <div class="result-card ${isActive}" data-slug="${r.slug}">
        <div class="result-card-title">${r.slug}</div>
        <div class="result-card-desc">${escapeHtml(r.description || "")}</div>
        <div class="result-card-meta">${r.category} · degree ${r.degree} · ${r.match_type}</div>
        ${snippet}
      </div>
    `);
  }
  els.resultsList.innerHTML = html.join("");
  els.resultsList.querySelectorAll(".result-card").forEach(card => {
    card.addEventListener("click", () => selectPage(card.dataset.slug));
  });
}

function highlight(text, query) {
  const escaped = escapeHtml(text);
  if (!query) return escaped;
  const re = new RegExp(`(${query.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')})`, 'gi');
  return escaped.replace(re, '<mark>$1</mark>');
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

// --- URL hash ---
function setHash({ q, page }) {
  const parts = [];
  if (q) parts.push(`q=${encodeURIComponent(q)}`);
  if (page) parts.push(`page=${encodeURIComponent(page)}`);
  const newHash = parts.length ? "#" + parts.join("&") : "";
  if (location.hash !== newHash) history.pushState(null, "", newHash || location.pathname);
}

function readHash() {
  const h = location.hash.slice(1);
  const out = {};
  for (const pair of h.split("&")) {
    const [k, v] = pair.split("=");
    if (k) out[k] = decodeURIComponent(v || "");
  }
  return out;
}

async function handleHash() {
  const { q, page } = readHash();
  if (q && q !== state.query) {
    els.searchInput.value = q;
    els.searchInput2.value = q;
    await doSearch(q);
  }
  if (page && page !== state.selectedSlug) {
    await selectPage(page);
  }
}

// --- 페이지 선택 ---
async function selectPage(slug) {
  state.selectedSlug = slug;
  setHash({ q: state.query, page: slug });
  renderResultList();

  els.pageView.innerHTML = `<div class="page-loading">로드 중…</div>`;
  try {
    const r = await fetch(`/api/page/${slug}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    state.pageData = await r.json();
    renderPage();
  } catch (e) {
    els.pageView.innerHTML = `<div class="page-loading">오류: ${e.message}</div>`;
  }
}

function renderPage() {
  const p = state.pageData;
  if (!p) return;
  const tags = (p.frontmatter.tags || []).map(t => `<span class="result-card-meta">#${t}</span>`).join(" ");
  els.pageView.innerHTML = `
    <div class="ai-toggle-row">
      <button class="ai-toggle" id="ai-toggle-btn">✨ AI 답변</button>
    </div>
    <h1>${escapeHtml(p.title)}</h1>
    <div class="page-meta">
      ${p.category} · in ${p.inbound} / out ${p.outbound} · access ${p.frontmatter.access_count || 0} · ${tags}
    </div>
    <div class="page-content">${p.html}</div>
    ${maybeAiCtaBox()}
  `;
  // wikilink 클릭 위임
  els.pageView.querySelectorAll("a[data-link]").forEach(a => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      selectPage(a.dataset.link);
    });
  });
  // AI 토글 (Task 12)
  const aiBtn = $("#ai-toggle-btn");
  if (aiBtn) {
    aiBtn.addEventListener("click", () => {
      const slugs = state.results.map(r => r.slug).slice(0, 5);
      callAI(state.query || p.title, slugs);
    });
  }
  // AI CTA box (결과 부족 시)
  const ctaBtn = $("#ai-cta-box-btn");
  if (ctaBtn) {
    ctaBtn.addEventListener("click", () => {
      const slugs = state.results.map(r => r.slug);
      callAI(state.query, slugs);
    });
  }

  // mini-graph fetch + render
  fetchAndRenderMiniGraph(p.slug);
}

async function fetchAndRenderMiniGraph(slug) {
  try {
    const r = await fetch(`/api/page/${slug}/graph`);
    if (!r.ok) return;
    const data = await r.json();
    renderMiniGraph(data);
  } catch (e) {
    console.warn("mini-graph 로드 실패:", e);
  }
}

function renderMiniGraph(data) {
  const view = els.pageView;
  // 기존 mini-graph가 있다면 제거
  const old = view.querySelector(".mini-graph-section");
  if (old) old.remove();

  const { center, neighbors, edges } = data;
  if (!neighbors || neighbors.length === 0) return;

  // SVG 크기 + center
  const W = 320, H = 280, cx = W / 2, cy = H / 2;
  const R = Math.min(W, H) * 0.38;
  const N = neighbors.length;

  // category color
  const CAT_COLOR = {
    concepts: "#2563eb", tools: "#10b981", people: "#a855f7",
    business: "#f59e0b", insights: "#ec4899", projects: "#0ea5e9",
    lecture: "#6b7280", papers: "#dc2626"
  };

  // 노드 위치: center + circle around
  const positions = { [center.slug]: { x: cx, y: cy } };
  neighbors.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / N - Math.PI / 2;
    positions[n.slug] = {
      x: cx + R * Math.cos(angle),
      y: cy + R * Math.sin(angle),
    };
  });

  // SVG 빌드
  const lines = edges.map(e => {
    const a = positions[e.source], b = positions[e.target];
    if (!a || !b) return "";
    return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="#d1d5db" stroke-width="1"/>`;
  }).join("");

  const centerColor = CAT_COLOR[center.category] || "#374151";
  const centerCircle = `<circle cx="${cx}" cy="${cy}" r="8" fill="${centerColor}" stroke="white" stroke-width="2"/>`;
  const centerLabel = `<text x="${cx}" y="${cy - 14}" text-anchor="middle" font-size="11" font-weight="600" fill="#0d0d0d">${escapeHtml(center.slug)}</text>`;

  const neighborMarkup = neighbors.map(n => {
    const p = positions[n.slug];
    const color = CAT_COLOR[n.category] || "#9ca3af";
    const arrow = n.direction === "both" ? "↔" : n.direction === "out" ? "→" : "←";
    return `
      <g class="mini-graph-node" data-slug="${escapeHtml(n.slug)}" style="cursor:pointer">
        <circle cx="${p.x}" cy="${p.y}" r="5" fill="${color}"/>
        <title>${escapeHtml(n.slug)} (${n.category}, ${arrow})</title>
      </g>
    `;
  }).join("");

  const section = document.createElement("div");
  section.className = "mini-graph-section";
  section.innerHTML = `
    <h3 class="mini-graph-title">📊 이 페이지의 1-depth 그래프 (degree ${center.degree})</h3>
    <svg class="mini-graph-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
      ${lines}
      ${neighborMarkup}
      ${centerCircle}
      ${centerLabel}
    </svg>
    <div class="mini-graph-legend">
      ${Object.entries(CAT_COLOR).filter(([cat]) => neighbors.some(n => n.category === cat) || center.category === cat).map(([cat, color]) => `<span><span class="dot" style="background:${color}"></span>${cat}</span>`).join("")}
    </div>
  `;
  view.appendChild(section);

  // 클릭 시 페이지 이동
  section.querySelectorAll(".mini-graph-node").forEach(g => {
    g.addEventListener("click", () => selectPage(g.dataset.slug));
  });
}

function maybeAiCtaBox() {
  // 결과 < 3개일 때만 결과 영역 아래에 큰 박스 CTA
  if (state.results.length > 0 && state.results.length < 3) {
    return `
      <div class="ai-cta-box">
        <div class="ai-cta-box-title">✨ 결과가 충분하지 않으신가요?</div>
        <div class="ai-cta-box-desc">위 ${state.results.length}개 페이지를 컨텍스트로 AI가 직접 답변해드릴 수 있어요.</div>
        <button id="ai-cta-box-btn" class="ai-cta-box-btn">"${escapeHtml(state.query)}" — AI에게 물어보기 →</button>
      </div>
    `;
  }
  return "";
}

// --- AI 호출 ---
async function callAI(question, contextSlugs) {
  const modal = ensureAiModal();
  modal.classList.remove("hidden");
  modal.querySelector(".ai-modal-body").innerHTML = `
    <div class="ai-modal-question">Q: ${escapeHtml(question)}</div>
    <div class="ai-modal-loading">
      AI 답변 생성 중<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>
    </div>
    <div class="ai-modal-answer" id="ai-stream-output" style="display:none"></div>
    <div class="ai-modal-context" id="ai-stream-sources" style="display:none"></div>
  `;

  try {
    const r = await fetch("/api/ai-answer/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, context_slugs: contextSlugs }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);

    const reader = r.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    const out = modal.querySelector("#ai-stream-output");
    const sourcesEl = modal.querySelector("#ai-stream-sources");
    let answerSoFar = "";
    let gotFirstChunk = false;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE events parsed by `\n\n` separator
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";
      for (const evt of events) {
        const ev = parseSseEvent(evt);
        if (!ev) continue;
        if (ev.event === "meta") {
          const slugs = ev.data.source_slugs || [];
          const details = [];
          if (ev.data.delivery_mode === "verified-buffered") {
            details.push("<strong>전달 방식:</strong> 검증 후 일괄 표시 (verified-buffered)");
          }
          if (slugs.length) {
            details.push(`<strong>검증된 출처 wiki 페이지:</strong> ${slugs.map(s => `<a href="#page=${encodeURIComponent(s)}" onclick="document.getElementById('ai-modal').classList.add('hidden')"><code>${escapeHtml(s)}</code></a>`).join(", ")}`);
          }
          const reasonCounts = ev.data.exclusion_reason_counts || {};
          const reasonEntries = Object.entries(reasonCounts);
          if (reasonEntries.length) {
            details.push(`<strong>제외 사유:</strong> ${reasonEntries.map(([reason, count]) => `${escapeHtml(reason)} ${count}`).join(", ")}`);
          }
          const action = ev.data.recommended_next_action;
          if (action && action.command) {
            details.push(`<strong>다음 행동:</strong> <code>${escapeHtml(action.command)}</code>`);
          }
          if (details.length) {
            sourcesEl.style.display = "block";
            sourcesEl.innerHTML = details.join("<br>");
          }
        } else if (ev.event === "chunk") {
          if (!gotFirstChunk) {
            modal.querySelector(".ai-modal-loading").style.display = "none";
            out.style.display = "block";
            gotFirstChunk = true;
          }
          answerSoFar += ev.data.text || "";
          out.innerHTML = escapeHtml(answerSoFar).replace(/\n/g, "<br>");
          out.scrollTop = out.scrollHeight;
        } else if (ev.event === "done") {
          modal.querySelector(".ai-modal-loading").style.display = "none";
          if (!gotFirstChunk) {
            out.style.display = "block";
            out.innerHTML = "<em>(빈 응답)</em>";
          }
        } else if (ev.event === "error") {
          modal.querySelector(".ai-modal-loading").style.display = "none";
          out.style.display = "block";
          out.innerHTML = `<span style="color:#dc2626">오류: ${escapeHtml(ev.data.message || "unknown")}</span>`;
        }
      }
    }
  } catch (e) {
    modal.querySelector(".ai-modal-body").innerHTML =
      `<div class="ai-modal-status">네트워크 오류: ${escapeHtml(e.message)}</div>`;
  }
}

function parseSseEvent(raw) {
  const lines = raw.split("\n").filter(l => l.trim());
  if (!lines.length) return null;
  const out = { event: "message", data: null };
  for (const line of lines) {
    if (line.startsWith("event:")) out.event = line.slice(6).trim();
    else if (line.startsWith("data:")) {
      try { out.data = JSON.parse(line.slice(5).trim()); }
      catch { out.data = line.slice(5).trim(); }
    }
  }
  return out;
}

function ensureAiModal() {
  let modal = document.getElementById("ai-modal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.id = "ai-modal";
  modal.className = "ai-modal hidden";
  modal.innerHTML = `
    <div class="ai-modal-card">
      <button class="ai-modal-close" aria-label="닫기">×</button>
      <h3>✨ AI 답변</h3>
      <div class="ai-modal-body"></div>
    </div>
  `;
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.classList.add("hidden");
  });
  modal.querySelector(".ai-modal-close").addEventListener("click", () => modal.classList.add("hidden"));
  window.addEventListener("hashchange", () => modal.classList.add("hidden"));
  // ESC key support
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) {
      modal.classList.add("hidden");
    }
  });
  document.body.appendChild(modal);
  return modal;
}

init();

/* ══════════════════════════════════════════════════════════════════════
   내 브레인 대시보드
   "지금까지 무엇을 완성했는가"를 한 장으로. 새 상태를 만들지 않고
   /api/dashboard 가 읽어 온 것만 그린다.

   디자인 언어 참고: cathrynlavery/diagram-design (MIT).
   색은 4개, 기술 라벨은 mono + letter-spacing, 큰 번호를 흐리게 깔아 리듬을 만든다.
   외부 라이브러리를 쓰지 않는다 — 오프라인에서도 같은 화면이어야 한다.
   ══════════════════════════════════════════════════════════════════════ */

const BD_COLORS = {
  concepts: "#eb6c36",
  tools: "#2e5aa8",
  projects: "#4f5d75",
  people: "#7a8399",
  business: "#2d3142",
  insights: "#c2410c",
};
const bdColor = (c) => BD_COLORS[c] || "#7a8399";

function bdEsc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (m) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

/* 가벼운 force 배치 — 라이브러리 대신 30줄.
   서로 밀어내고(반발), 연결된 것끼리 당긴다(인력). 60번만 돌려도 충분히 읽힌다. */
function bdLayout(nodes, links, W, H) {
  const n = nodes.length;
  if (!n) return [];
  const pts = nodes.map((d, i) => {
    const a = (2 * Math.PI * i) / n;
    return { ...d, x: W / 2 + Math.cos(a) * W * 0.28, y: H / 2 + Math.sin(a) * H * 0.34 };
  });
  const idx = new Map(pts.map((p, i) => [p.slug, i]));
  const ls = links
    .map((l) => [idx.get(l.s), idx.get(l.t)])
    .filter(([a, b]) => a != null && b != null && a !== b);

  /* 반복 횟수를 노드 수에 맞춰 줄인다. 60개 × 60회면 노드쌍 연산이 10만 회를 넘어
     저사양 노트북에서 메인 스레드가 눈에 띄게 멈춘다. 적은 노드는 그대로 60회. */
  const steps = n <= 12 ? 60 : n <= 30 ? 34 : 20;
  for (let step = 0; step < steps; step++) {
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = pts[j].x - pts[i].x, dy = pts[j].y - pts[i].y;
        let d2 = dx * dx + dy * dy || 0.01;
        const f = 900 / d2;                       // 반발
        const d = Math.sqrt(d2);
        dx /= d; dy /= d;
        pts[i].x -= dx * f; pts[i].y -= dy * f;
        pts[j].x += dx * f; pts[j].y += dy * f;
      }
    }
    for (const [a, b] of ls) {                    // 인력
      const dx = pts[b].x - pts[a].x, dy = pts[b].y - pts[a].y;
      pts[a].x += dx * 0.02; pts[a].y += dy * 0.02;
      pts[b].x -= dx * 0.02; pts[b].y -= dy * 0.02;
    }
  }

  /* 마지막에 화면 크기로 정규화한다.
     인력이 반발을 이기면 노드가 가운데로 뭉쳐 폭의 1/7만 쓰게 된다(실측).
     힘의 계수를 맞추는 대신, 나온 모양을 그대로 늘려 화면을 채운다 —
     노드가 6개든 60개든 같은 밀도로 보인다. */
  const pad = 34;
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = Math.max(1, maxX - minX), spanY = Math.max(1, maxY - minY);
  const sc = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
  const offX = (W - spanX * sc) / 2, offY = (H - spanY * sc) / 2;
  for (const p of pts) {
    p.x = offX + (p.x - minX) * sc;
    p.y = offY + (p.y - minY) * sc;
  }

  /* 정규화 후에도 겹치면 살짝 밀어낸다(라벨이 서로 먹지 않게) */
  for (let pass = 0; pass < 12; pass++) {
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = pts[j].x - pts[i].x, dy = pts[j].y - pts[i].y;
        const d = Math.hypot(dx, dy) || 0.01;
        const need = 34;
        if (d < need) {
          const push = ((need - d) / d) * 0.5;
          pts[i].x -= dx * push; pts[i].y -= dy * push;
          pts[j].x += dx * push; pts[j].y += dy * push;
        }
      }
    }
  }
  for (const p of pts) {
    p.x = Math.max(pad, Math.min(W - pad, p.x));
    p.y = Math.max(pad * 0.7, Math.min(H - pad, p.y));
  }
  return pts;
}

function bdGraphSvg(k) {
  const nodes = k.nodes || [];
  if (!nodes.length) {
    return `<p class="bd-empty">아직 위키가 비어 있습니다.<br>
      메모를 넣고 <code>python scripts/compile.py</code> 를 실행하면 여기에 지도가 그려집니다.</p>`;
  }
  const W = 860, H = 260;
  const pts = bdLayout(nodes, k.graph_links || [], W, H);
  const byslug = new Map(pts.map((p) => [p.slug, p]));
  const maxDeg = Math.max(1, ...pts.map((p) => p.degree));

  const edges = (k.graph_links || []).map((l) => {
    const a = byslug.get(l.s), b = byslug.get(l.t);
    // 자기 자신을 가리키는 링크는 길이 0 선이라 그려도 보이지 않는다(집계에는 남는다).
    if (!a || !b || l.s === l.t) return "";
    return `<line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}"
      stroke="rgba(45,49,66,0.18)" stroke-width="1"/>`;
  }).join("");

  const circles = pts.map((p) => {
    const r = 4 + (p.degree / maxDeg) * 7;
    const t = typeof p.title === "string" ? p.title : String(p.slug || "");
    const label = t.length > 14 ? t.slice(0, 13) + "…" : t;
    return `<g class="bd-node" style="cursor:pointer" data-slug="${bdEsc(p.slug)}"
      tabindex="0" role="link" aria-label="${bdEsc(p.title)} 페이지 열기">
      <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r.toFixed(1)}"
        fill="${bdColor(p.category)}" fill-opacity="${p.degree ? 0.9 : 0.35}"
        stroke="#f5f5f5" stroke-width="1.5"/>
      <text x="${p.x.toFixed(1)}" y="${(p.y + r + 9).toFixed(1)}" text-anchor="middle"
        font-size="8" fill="#4f5d75">${bdEsc(label)}</text>
    </g>`;
  }).join("");

  const cats = Object.keys(k.categories || {});
  const legend = cats.map((c) =>
    `<span><i style="background:${bdColor(c)}"></i>${bdEsc(c)} ${k.categories[c]}</span>`).join("");

  /* viewBox 를 실제 노드가 놓인 영역으로 좁힌다.
     좌표를 늘리면(왜곡) 노드 사이 거리가 거짓말이 되므로, 대신 카메라를 당긴다.
     노드가 적으면 크게, 많으면 작게 보이는 것이 자연스럽다. */
  const gx = pts.map((p) => p.x), gy = pts.map((p) => p.y);
  const vp = 30;
  const vx = Math.min(...gx) - vp, vy = Math.min(...gy) - vp;
  const vw = Math.max(1, Math.max(...gx) - Math.min(...gx)) + vp * 2;
  const vh = Math.max(1, Math.max(...gy) - Math.min(...gy)) + vp * 2;

  /* role 은 group 이다. img 로 두면 그 아래 role="link" 노드들이 접근성 트리에서
     이미지 하나로 평면화돼, 키보드로는 열려도 스크린리더가 링크로 못 읽는다. */
  return `<svg class="bd-graph" viewBox="${vx.toFixed(0)} ${vy.toFixed(0)} ${vw.toFixed(0)} ${vh.toFixed(0)}" role="group"
      preserveAspectRatio="xMidYMid meet"
      aria-label="내 위키 지식 지도 — 페이지 ${nodes.length}개, 연결 ${(k.graph_links || []).length}개">
      ${edges}${circles}
    </svg>
    <div class="bd-legend">${legend}${k.orphans ? `<span>연결 없음 ${k.orphans}</span>` : ""}</div>`;
}

function bdLogLine(line) {
  const cls = line.includes("BLOCK") ? "block" : line.includes("PASS") ? "pass" : "";
  return `<span class="${cls}">${bdEsc(line)}</span>`;
}

async function renderBrainDashboard() {
  const host = document.getElementById("brain-dash");
  if (!host) return;
  let d;
  try {
    const r = await fetch("/api/dashboard");
    if (!r.ok) return;
    d = await r.json();
  } catch (e) {
    console.warn("대시보드 로드 실패:", e);
    return;
  }

  const k = d.knowledge, a = d.automation, t = d.attention;
  const logs = [...(a.watch || []), ...(a.graph_runner || [])].slice(-4);

  const organs = d.organs.map((o) => `
    <div class="bd-organ ${o.installed ? "on" : "off"}">
      <span class="bd-organ-dot"></span>
      <span class="bd-organ-wk">${bdEsc(o.week)}주</span>
      <span class="bd-organ-nm">${bdEsc(o.name)}</span>
      <span class="bd-organ-gain">${bdEsc(o.gain)}</span>
    </div>`).join("");

  host.innerHTML = `
    <div class="bd-head">
      <span class="bd-title">내 브레인</span>
      <span class="bd-sub">${d.installed} / 6 organs · ${k.pages} pages</span>
    </div>
    <div class="bd-grid">
      <div class="bd-card">
        <div class="bd-card-label">Knowledge</div>
        <div class="bd-stats">
          <span><span class="bd-stat-n">${k.pages}</span><span class="bd-stat-l">PAGES</span></span>
          <span><span class="bd-stat-n accent">${k.links}</span><span class="bd-stat-l">LINKS</span></span>
          <span><span class="bd-stat-n">${k.orphans}</span><span class="bd-stat-l">ORPHAN</span></span>
        </div>
        <div class="bd-card-no">01</div>
      </div>

      <div class="bd-card">
        <div class="bd-card-label">Attention</div>
        <div class="bd-stats">
          <span><span class="bd-stat-n">${t.raw_pending}</span><span class="bd-stat-l">RAW</span></span>
          <span><span class="bd-stat-n ${t.review.length ? "accent" : ""}">${t.review.length}</span><span class="bd-stat-l">REVIEW</span></span>
          <span><span class="bd-stat-n">${a.mcp_calls}${a.mcp_calls_capped ? "+" : ""}</span><span class="bd-stat-l">MCP</span></span>
        </div>
        ${t.review.length ? `<div class="bd-empty" style="margin-top:8px">검수함에서 기다리는 중: ${t.review.map(bdEsc).join(", ")}</div>` : ""}
        <div class="bd-card-no">02</div>
      </div>

      <div class="bd-card wide">
        <div class="bd-card-label">Organs · 매주 하나씩 붙입니다</div>
        <div class="bd-organs">${organs}</div>
        <div class="bd-card-no">03</div>
      </div>

      <div class="bd-card wide">
        <div class="bd-card-label">Automation · 내가 안 볼 때 돈 기록</div>
        ${logs.length
          ? `<div class="bd-log">${logs.map(bdLogLine).join("\n")}</div>`
          : `<p class="bd-empty">아직 자동 실행 기록이 없습니다.<br>
             11주차에 <code>extensions/w11_watch.py</code> 를 붙이면 여기에 남습니다.</p>`}
        <div class="bd-card-no">04</div>
      </div>

      <div class="bd-card wide">
        <div class="bd-card-label">Map · 내 지식이 이어진 모양</div>
        ${bdGraphSvg(k)}
        <div class="bd-card-no">05</div>
      </div>
    </div>`;

  host.querySelectorAll(".bd-node").forEach((g) => {
    // 이 앱의 해시 계약은 #page=<slug> 다(위 AI 답변 출처 링크와 동일).
    // "#/page/..." 로 쓰면 readHash 가 못 읽어 클릭해도 아무 일도 일어나지 않는다.
    const open = () => { location.hash = "#page=" + encodeURIComponent(g.dataset.slug); };
    g.addEventListener("click", open);
    g.addEventListener("keydown", (e) => {          // 마우스 없이도 열 수 있어야 한다
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
  });
}

renderBrainDashboard();
