/* Flight Scout dashboard — dependency-free ES2020. */

const $ = (id) => document.getElementById(id);

const state = {
  meta: null,
  params: null,
  payload: null,
  regions: new Set(),
  loading: false,
  inflight: null,
  canSetup: true,
  static: false,
  snapshot: null,
};

const CURRENCY_SYMBOL = { HKD: "HK$", USD: "US$", EUR: "€", CNY: "¥", GBP: "£", JPY: "JP¥" };

/* ------------------------------------------------------------------ utils */

function currentTheme() {
  return document.documentElement.dataset.theme || "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("fs-theme", theme);
  } catch {
    /* private mode: theme simply won't persist */
  }
  const btn = $("themeBtn");
  if (btn) {
    btn.textContent = theme === "dark" ? "☀️" : "🌙";
    btn.title = theme === "dark" ? "切换到浅色" : "切换到深色";
  }
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const money = (n) => Math.round(n).toLocaleString("en-US");
const sym = (cur) => CURRENCY_SYMBOL[cur] || `${cur} `;
const kfmt = (n) => {
  const v = n / 1000;
  return `${v % 1 === 0 ? v.toFixed(0) : v.toFixed(1)}k`;
};

function toast(msg, isError = false) {
  const el = $("toast");
  el.textContent = msg;
  el.className = `toast show${isError ? " err" : ""}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = "toast"; }, 3600);
}

function qs(params) {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "" || v === false) continue;
    if (Array.isArray(v)) {
      if (!v.length) continue;
      usp.set(k, v.join(","));
    } else if (v === true) {
      usp.set(k, "true");
    } else {
      usp.set(k, String(v));
    }
  }
  return usp.toString();
}

/* -------------------------------------------------------------- bootstrapping */

async function init() {
  bindEvents();
  applyTheme(currentTheme());

  let meta = null;
  try {
    const res = await fetch("/api/meta", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    meta = await res.json();
  } catch {
    meta = null;
  }

  if (!meta) {
    // No backend: we are on a static host (GitHub Pages) or opened from disk.
    const ok = await loadSnapshot();
    if (!ok) {
      toast("找不到 data/snapshot.json，无法载入快照", true);
      return;
    }
    state.canSetup = false;
  } else {
    state.meta = meta;
    try {
      const cfg = await (await fetch("/api/config")).json();
      state.canSetup = cfg.local !== false;
    } catch {
      state.canSetup = true;
    }
  }

  applyDefaults(state.meta.defaults);
  buildOriginSelect();
  buildPresets(state.meta.presets || []);
  buildRegionChips();
  renderProvider(state.meta);
  await search();
  if (location.hash === "#setup") openSetup();
}

/* --------------------------------------------------------- static snapshot */

async function loadSnapshot() {
  let snap;
  try {
    const res = await fetch("data/snapshot.json", { cache: "no-store" });
    if (!res.ok) return false;
    snap = await res.json();
  } catch {
    return false;
  }
  state.static = true;
  state.snapshot = snap;

  const w = snap.window || {};
  const fallback = nextChristmasWindow();
  state.meta = {
    version: snap.app_version,
    origin: snap.origin,
    origin_name: (snap.origins[0] || {}).city || "香港",
    origins: snap.origins,
    currency: snap.currency || "HKD",
    destinations: snap.destination_count,
    regions: snap.regions,
    region_counts: countRegions(snap.offers, snap.origins),
    providers: [],
    defaults: {
      depart_from: w.depart_from || fallback.depart_from,
      depart_to: w.depart_to || fallback.depart_to,
      return_from: w.return_from || fallback.return_from,
      return_to: w.return_to || fallback.return_to,
      nights_min: w.nights_min || 4,
      nights_max: w.nights_max || 12,
    },
    presets: buildPresetsFromWindow(w.depart_from || fallback.depart_from),
  };
  return true;
}

function countRegions(offers, origins) {
  const counts = {};
  (offers || []).forEach((o) => {
    counts[o.region] = (counts[o.region] || 0) + 1;
  });
  Object.keys(counts).forEach((k) => {
    counts[k] = Math.round(counts[k] / Math.max(1, (origins || []).length));
  });
  return counts;
}

function nextChristmasWindow() {
  const now = new Date();
  const year = now < new Date(now.getFullYear(), 11, 27) ? now.getFullYear() : now.getFullYear() + 1;
  const iso = (y, m, d) => `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  return {
    depart_from: iso(year, 12, 18),
    depart_to: iso(year, 12, 24),
    return_from: iso(year, 12, 26),
    return_to: iso(year + 1, 1, 4),
  };
}

function buildPresetsFromWindow(departFrom) {
  const year = Number(String(departFrom).slice(0, 4)) || new Date().getFullYear();
  const iso = (y, m, d) => `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  return [
    {
      id: "xmas", label: "圣诞主场", desc: "12/20 出发，节后回",
      params: {
        depart_from: iso(year, 12, 19), depart_to: iso(year, 12, 23),
        return_from: iso(year, 12, 26), return_to: iso(year, 12, 31),
        nights_min: 4, nights_max: 12,
      },
    },
    {
      id: "newyear", label: "跨年长线", desc: "12/27 出发，1 月回",
      params: {
        depart_from: iso(year, 12, 27), depart_to: iso(year, 12, 31),
        return_from: iso(year + 1, 1, 2), return_to: iso(year + 1, 1, 6),
        nights_min: 5, nights_max: 14,
      },
    },
    {
      id: "shoulder", label: "错峰捡漏", desc: "节前一周出发",
      params: {
        depart_from: iso(year, 12, 12), depart_to: iso(year, 12, 17),
        return_from: iso(year, 12, 19), return_to: iso(year, 12, 24),
        nights_min: 4, nights_max: 10,
      },
    },
  ];
}

function applyDefaults(d) {
  $("departFrom").value = d.depart_from;
  $("departTo").value = d.depart_to;
  $("returnFrom").value = d.return_from;
  $("returnTo").value = d.return_to;
  $("nightsMin").value = d.nights_min;
  $("nightsMax").value = d.nights_max;
}

function buildPresets(presets) {
  const wrap = $("presets");
  wrap.innerHTML = "";
  presets.forEach((p) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "preset";
    btn.dataset.id = p.id;
    btn.innerHTML = `<strong>${esc(p.label)}</strong><span style="opacity:.6"> · ${esc(p.desc)}</span>`;
    btn.addEventListener("click", () => {
      document.querySelectorAll(".preset").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const q = p.params;
      $("departFrom").value = q.depart_from;
      $("departTo").value = q.depart_to;
      $("returnFrom").value = q.return_from;
      $("returnTo").value = q.return_to;
      $("nightsMin").value = q.nights_min;
      $("nightsMax").value = q.nights_max;
      search();
    });
    wrap.appendChild(btn);
  });
}

function buildOriginSelect() {
  const sel = $("origin");
  sel.innerHTML = "";
  (state.meta.origins || [{ code: "HKG", label: "香港" }]).forEach((o) => {
    const opt = document.createElement("option");
    opt.value = o.code;
    opt.textContent = o.label;
    sel.appendChild(opt);
  });
  sel.value = state.meta.origin || "HKG";
}

function buildRegionChips() {
  const wrap = $("regionChips");
  wrap.innerHTML = "";
  const counts = state.meta.region_counts || {};
  const all = document.createElement("button");
  all.type = "button";
  all.className = "chip active";
  all.dataset.region = "";
  all.innerHTML = `全部目的地<span class="count">${state.meta.destinations}</span>`;
  all.addEventListener("click", () => {
    state.regions.clear();
    document.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    all.classList.add("active");
    search();
  });
  wrap.appendChild(all);

  (state.meta.regions || []).forEach((r) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.dataset.region = r;
    btn.innerHTML = `${esc(r)}<span class="count">${counts[r] || 0}</span>`;
    btn.addEventListener("click", () => {
      btntoggle(btn);
      if (state.regions.has(r)) state.regions.delete(r);
      else state.regions.add(r);
      all.classList.toggle("active", state.regions.size === 0);
      search();
    });
    wrap.appendChild(btn);
  });
}

function btntoggle(btn) {
  btn.classList.toggle("active");
}

/* ------------------------------------------------------------------ events */

function bindEvents() {
  $("searchBtn").addEventListener("click", () => search());
  $("origin").addEventListener("change", () => search());
  $("directOnly").addEventListener("change", () => search());
  $("sort").addEventListener("change", () => search());
  $("exportBtn").addEventListener("click", exportCsv);
  $("themeBtn").addEventListener("click", () => {
    applyTheme(currentTheme() === "dark" ? "light" : "dark");
  });
  $("providerPill").addEventListener("click", openSetup);
  $("closeSetup").addEventListener("click", closeSetup);
  $("cancelSetup").addEventListener("click", closeSetup);
  $("saveSetup").addEventListener("click", saveSetup);
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => selectTab(tab.dataset.tab));
  });
  $("setupModal").addEventListener("click", (e) => {
    if (e.target.id === "setupModal") closeSetup();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSetup();
  });
  ["departFrom", "departTo", "returnFrom", "returnTo", "nightsMin", "nightsMax", "maxPrice"].forEach((id) => {
    $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });
  });
}

/* ------------------------------------------------------- real-price setup */

function selectTab(name) {
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.classList.toggle("hidden", p.dataset.panel !== name);
  });
  $("setupStatus").className = "setup-status";
  $("setupStatus").textContent = "";
}

async function openSetup() {
  if (!state.canSetup) {
    toast("这是共享页面，密钥只能在运行本工具的电脑上修改");
    return;
  }
  $("setupModal").classList.remove("hidden");
  const status = $("setupStatus");
  status.className = "setup-status";
  status.textContent = "";
  try {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    if (cfg.serpapi && cfg.serpapi.configured) {
      $("serpapiKey").placeholder = `已保存：${cfg.serpapi.key}（重新填写可覆盖）`;
      document.querySelector('[data-tab="serpapi"]').classList.add("done");
    }
    if (cfg.travelpayouts && cfg.travelpayouts.configured) {
      document.querySelector('[data-tab="travelpayouts"]').classList.add("done");
    }
    if (cfg.amadeus && cfg.amadeus.configured) {
      $("amadeusId").placeholder = `已保存：${cfg.amadeus.client_id}（重新填写可覆盖）`;
      $("amadeusEnv").value = cfg.amadeus.env === "production" ? "production" : "test";
      document.querySelector('[data-tab="amadeus"]').classList.add("done");
    }
    if (cfg.live) selectTab(cfg.active_provider === "amadeus" ? "amadeus" : cfg.active_provider);
  } catch {
    /* opening the dialog must never fail loudly */
  }
}

function closeSetup() {
  $("setupModal").classList.add("hidden");
}

async function saveSetup() {
  const btn = $("saveSetup");
  const status = $("setupStatus");
  const payload = {
    serpapi_key: $("serpapiKey").value.trim(),
    travelpayouts_token: $("travelpayoutsToken").value.trim(),
    amadeus_client_id: $("amadeusId").value.trim(),
    amadeus_client_secret: $("amadeusSecret").value.trim(),
    amadeus_env: $("amadeusEnv").value,
  };

  if (!payload.serpapi_key && !payload.travelpayouts_token
      && !payload.amadeus_client_id && !payload.amadeus_client_secret) {
    status.className = "setup-status err";
    status.textContent = "请先在任意一栏填入密钥，再点保存。";
    return;
  }

  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "验证中…";
  status.className = "setup-status";
  status.textContent = "正在验证密钥，请稍候（约 3–10 秒）…";

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "保存失败");
    status.className = "setup-status ok";
    status.textContent = "✅ 成功！已切换为真实票价，正在重新查询…";
    $("serpapiKey").value = "";
    $("travelpayoutsToken").value = "";
    $("amadeusSecret").value = "";
    setTimeout(() => { closeSetup(); search(); }, 800);
  } catch (err) {
    status.className = "setup-status err";
    status.textContent = `❌ ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

function collectParams() {
  const num = (id) => {
    const v = $(id).value.trim();
    return v === "" ? null : Number(v);
  };
  return {
    origin: $("origin").value || "HKG",
    depart_from: $("departFrom").value,
    depart_to: $("departTo").value,
    return_from: $("returnFrom").value,
    return_to: $("returnTo").value,
    nights_min: num("nightsMin") ?? 1,
    nights_max: num("nightsMax") ?? 30,
    max_price: num("maxPrice"),
    regions: [...state.regions],
    direct_only: $("directOnly").checked,
    sort: $("sort").value,
    provider: "auto",
    limit: 200,
  };
}

/* ------------------------------------------------------------------ search */

async function search() {
  if (state.loading) return;
  const params = collectParams();
  state.params = params;
  state.loading = true;
  const btn = $("searchBtn");
  const oldLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = "查询中…";

  try {
    let data;
    if (state.static) {
      data = localSearch(params);          // no backend: filter the snapshot
    } else {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    }
    state.payload = data;
    render(data);
  } catch (err) {
    toast(err.message, true);
  } finally {
    state.loading = false;
    btn.disabled = false;
    btn.textContent = oldLabel;
  }
}

/* ------------------------------------------------- local search (snapshot) */

const SORTERS = {
  price: (a, b) => a.price - b.price || b.deal_score - a.deal_score,
  deal: (a, b) => b.deal_score - a.deal_score || a.price - b.price,
  value: (a, b) => a.price_per_1000km - b.price_per_1000km || a.price - b.price,
  distance: (a, b) => a.distance_km - b.distance_km || a.price - b.price,
  nights: (a, b) => b.nights - a.nights || a.price - b.price,
  date: (a, b) => String(a.depart).localeCompare(String(b.depart)) || a.price - b.price,
};

function median(values) {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function localSearch(params) {
  const snap = state.snapshot;
  const origin = params.origin;
  let rows = (snap.offers || []).filter((o) => o.origin === origin);

  if (params.regions && params.regions.length) {
    rows = rows.filter((o) => params.regions.includes(o.region));
  }
  if (params.direct_only) rows = rows.filter((o) => o.stops === 0);
  if (params.max_price != null && params.max_price !== "") {
    rows = rows.filter((o) => o.price <= Number(params.max_price));
  }
  rows = rows.slice().sort(SORTERS[params.sort] || SORTERS.price).slice(0, params.limit || 200);

  const info = (snap.per_origin || {})[origin] || {};
  return {
    meta: {
      origin,
      provider: info.provider || "snapshot",
      provider_name: info.provider_name || "GitHub 快照",
      live: !!info.live,
      note: "定时抓取的快照，不是你打开这一刻的实时价格。",
      price_basis: info.price_basis || "round_trip",
      currency: snap.currency || "HKD",
      generated_at: snap.generated_at,
      elapsed_ms: 0,
      destination_pool: (snap.offers || []).filter((o) => o.origin === origin).length,
      warnings: info.warnings || [],
      params,
      cached: true,
      snapshot: true,
    },
    summary: summarizeRows(rows),
    results: rows,
  };
}

function summarizeRows(rows) {
  if (!rows.length) {
    return { count: 0, cheapest: null, median: null, best_value: null, best_deal: null, by_region: [] };
  }
  const groups = {};
  rows.forEach((r) => (groups[r.region] = groups[r.region] || []).push(r));
  const order = (state.meta.regions || Object.keys(groups)).filter((r) => groups[r]);

  return {
    count: rows.length,
    median: Math.round(median(rows.map((r) => r.price)) * 100) / 100,
    cheapest: rows.reduce((a, b) => (a.price <= b.price ? a : b)),
    best_value: rows.reduce((a, b) => (a.price_per_1000km <= b.price_per_1000km ? a : b)),
    best_deal: rows.reduce((a, b) => (
      b.deal_score > a.deal_score || (b.deal_score === a.deal_score && b.price < a.price) ? b : a
    )),
    by_region: order.map((region) => {
      const g = groups[region];
      const best = g.reduce((a, b) => (a.price <= b.price ? a : b));
      return {
        region,
        count: g.length,
        min: Math.round(Math.min(...g.map((r) => r.price)) * 100) / 100,
        median: Math.round(median(g.map((r) => r.price)) * 100) / 100,
        best_code: best.code,
        best_city: best.city,
      };
    }),
  };
}

function exportCsv() {
  if (!state.params) return;
  if (state.static) {
    downloadCsv(state.payload ? state.payload.results : []);
    return;
  }
  window.open(`/api/export.csv?${qs(state.params)}`, "_blank");
  toast("正在下载 CSV（可用 Excel 打开）");
}

function downloadCsv(rows) {
  if (!rows || !rows.length) {
    toast("当前没有结果可导出", true);
    return;
  }
  const cols = [
    ["city", "目的地"], ["code", "机场"], ["country", "国家/地区"], ["region", "区域"],
    ["price", "价格"], ["currency", "币种"], ["depart", "出发"], ["return", "返程"],
    ["nights", "晚数"], ["airline", "航司"], ["stops", "转机"], ["duration_label", "航程"],
    ["distance_km", "距离km"], ["price_per_1000km", "每千公里"], ["deal_score", "性价比"],
    ["tags", "标签"], ["source", "数据源"],
  ];
  const cell = (v) => {
    const s = String(v == null ? "" : v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [cols.map((c) => c[1]).concat(["Google Flights", "Trip.com"]).join(",")];
  rows.forEach((r) => {
    const base = cols.map(([key]) => cell(key === "tags" ? (r.tags || []).join(" / ") : r[key]));
    const links = r.booking_links || {};
    lines.push(base.concat([cell(links.google), cell(links.trip)]).join(","));
  });
  const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `flightscout-${(state.params.origin || "HKG")}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast("已导出 CSV");
}

function shortTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16).replace("T", " ");
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* ------------------------------------------------------------------ render */

function render(p) {
  const meta = p.meta;
  const summary = p.summary;
  const cur = meta.currency || "HKD";

  renderOriginLabel(meta.origin);
  renderProvider(meta);
  renderStats(p, cur);
  renderRegionChart(summary.by_region || [], cur);
  renderScatter(p.results || [], cur);
  renderTable(p.results || [], cur);

  $("resultMeta").textContent = summary.count
    ? (state.static
      ? `共 ${summary.count} 个目的地 · 快照更新于 ${shortTime(meta.generated_at)}`
      : `共 ${summary.count} 个目的地 · ${meta.live ? "实时报价" : "演示报价"} · ${meta.elapsed_ms} ms${meta.cached ? " · 缓存" : ""}`)
    : "无结果";

  const note = $("footerNote");
  if (state.static) {
    note.innerHTML = `<strong style="color:var(--warm)">快照模式</strong>：价格由 GitHub Actions 定时抓取（${esc(shortTime(meta.generated_at))}），不是实时。点行尾的 Google / Trip 可核对当下价格。`;
  } else if (meta.live) {
    note.innerHTML = `数据源：<strong style="color:var(--accent)">${esc(meta.provider_name)}</strong> · 报价为${meta.price_basis === "one_way" ? "单程" : "往返"}含税参考价`;
  } else {
    note.innerHTML = `<strong>演示数据</strong>：按航线距离、圣诞旺季系数与航司类型生成的仿真报价，非真实票价。在右上角填入 SerpApi key 后自动切换为实时。`;
  }
  (meta.warnings || []).forEach((w) => toast(w, true));
}

function renderOriginLabel(code) {
  const origin = (state.meta && state.meta.origins || []).find((o) => o.code === code);
  const city = origin ? origin.city : "香港";
  const sub = document.querySelector(".brand-text p");
  if (sub) sub.textContent = `${city}出发 · 假期去哪儿最便宜`;
  document.title = `Flight Scout · ${city}出发，假期去哪儿最便宜`;
}

function renderProvider(meta) {
  const pill = $("providerPill");
  const live = meta.live ?? false;

  if (state.static) {
    pill.className = `pill ${live ? "pill-live" : "pill-demo"}`;
    pill.textContent = `${live ? "实时快照" : "演示快照"} · ${shortTime(meta.generated_at)}`;
    pill.title = "这是 GitHub Actions 定时抓取的结果，不是你打开这一刻的实时价格。";
    return;
  }

  const providers = meta.providers || [];
  const active = providers.find((x) => x.id === meta.provider)
    || providers.find((x) => x.live && x.ready)
    || providers.find((x) => x.id === "demo");
  pill.className = `pill ${live ? "pill-live" : "pill-demo"}`;
  if (!state.canSetup) {
    pill.textContent = live ? `${meta.provider_name || "实时"} · 实时` : "演示数据";
    pill.title = "这是共享页面；密钥设置只能在运行本工具的电脑上修改。";
    return;
  }
  pill.textContent = live ? `${meta.provider_name || "实时"} · 实时` : "演示数据 · 点此开启真实票价";
  pill.title = live
    ? (meta.note || "")
    : "现在显示的是示例价格。点这里填入免费密钥，即可查询真实机票价。";
}

function renderStats(p, cur) {
  const s = p.summary;
  const wrap = $("stats");
  if (!s.count) {
    wrap.innerHTML = "";
    return;
  }
  const cheap = s.cheapest;
  const longHaul = (p.results || []).filter((r) => r.distance_km > 5000);
  const bestLong = longHaul.length ? longHaul.reduce((a, b) => (a.price <= b.price ? a : b)) : cheap;
  const regions = new Set((p.results || []).map((r) => r.region)).size;
  wrap.innerHTML = `
    <div class="stat">
      <span class="label">最低往返价</span>
      <div class="value">${sym(cur)}${money(cheap.price)}</div>
      <div class="sub"><span class="cc sm">${esc(cheap.cc)}</span> ${esc(cheap.city)} ${esc(cheap.code)} · ${cheap.nights} 晚</div>
    </div>
    <div class="stat b">
      <span class="label">中位价</span>
      <div class="value">${sym(cur)}${money(s.median)}</div>
      <div class="sub">覆盖 ${s.count} 个目的地 / ${regions} 个区域</div>
    </div>
    <div class="stat c">
      <span class="label">长线最低价 · 5,000km+</span>
      <div class="value">${sym(cur)}${money(bestLong.price)}</div>
      <div class="sub"><span class="cc sm">${esc(bestLong.cc)}</span> ${esc(bestLong.city)} · ${money(bestLong.distance_km)} km</div>
    </div>
    <div class="stat d">
      <span class="label">每公里最划算</span>
      <div class="value sm"><span class="cc sm">${esc(s.best_value.cc)}</span> ${esc(s.best_value.city)}</div>
      <div class="sub">${sym(cur)}${money(s.best_value.price)} · ${money(s.best_value.price_per_1000km)}/千公里</div>
    </div>`;
}

function renderRegionChart(rows, cur) {
  const wrap = $("regionChart");
  if (!rows.length) {
    wrap.innerHTML = `<div class="muted">暂无数据</div>`;
    return;
  }
  const sorted = [...rows].sort((a, b) => a.min - b.min);
  const max = Math.max(...sorted.map((r) => r.min)) || 1;
  wrap.innerHTML = `<div class="bars">${sorted.map((r) => {
    const pct = Math.max(6, (r.min / max) * 100);
    const dim = state.regions.size && !state.regions.has(r.region) ? " dim" : "";
    return `<div class="bar-row${dim}" data-region="${esc(r.region)}" title="${esc(r.region)} · ${r.count} 个目的地 · 最低 ${money(r.min)}">
      <span class="bar-label">${esc(r.region)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
      <span class="bar-value">${money(r.min)}</span>
    </div>`;
  }).join("")}</div>`;

  wrap.querySelectorAll(".bar-row").forEach((row) => {
    row.addEventListener("click", () => {
      const region = row.dataset.region;
      const chip = [...document.querySelectorAll(".chip")].find((c) => c.dataset.region === region);
      if (!chip) return;
      chip.click();
    });
  });
}

function renderScatter(results, cur) {
  const box = $("scatter");
  if (!results.length) {
    box.innerHTML = `<div class="muted">暂无数据</div>`;
    return;
  }
  const W = Math.max(320, box.clientWidth || 520);
  const H = 180;
  const m = { l: 44, r: 14, t: 12, b: 24 };
  const iw = W - m.l - m.r;
  const ih = H - m.t - m.b;

  const maxD = Math.max(...results.map((r) => r.distance_km)) * 1.06 || 1;
  const maxP = Math.max(...results.map((r) => r.price)) * 1.08 || 1;
  const minP = Math.min(...results.map((r) => r.price)) * 0.82;

  const x = (d) => m.l + (d / maxD) * iw;
  const y = (p) => m.t + ih - ((p - minP) / (maxP - minP)) * ih;

  const cheapest = results.reduce((a, b) => (a.price < b.price ? a : b));
  const ticks = 4;
  let grid = "";
  for (let i = 0; i <= ticks; i++) {
    const gy = m.t + (ih / ticks) * i;
    const val = maxP - ((maxP - minP) / ticks) * i;
    grid += `<line class="grid-line" x1="${m.l}" y1="${gy}" x2="${W - m.r}" y2="${gy}"/>`;
    grid += `<text class="tick" x="${m.l - 6}" y="${gy + 3}" text-anchor="end">${kfmt(val)}</text>`;
  }
  const xTicks = 4;
  for (let i = 0; i <= xTicks; i++) {
    const gx = m.l + (iw / xTicks) * i;
    grid += `<text class="tick" x="${gx}" y="${H - 8}" text-anchor="middle">${kfmt((maxD / xTicks) * i)}</text>`;
  }

  const dots = results.map((r) => `
    <circle class="dot${r===cheapest ? " best" : ""}" cx="${x(r.distance_km).toFixed(1)}" cy="${y(r.price).toFixed(1)}"
      r="${r === cheapest ? 6 : 4.4}">
      <title>${esc(r.city)} ${esc(r.code)} · ${sym(cur)}${money(r.price)} · ${money(r.distance_km)} km · ${esc(r.airline || "")}</title>
    </circle>`).join("");

  box.innerHTML = `<svg class="scatter-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="价格与距离散点图">
    ${grid}
    <line class="axis" x1="${m.l}" y1="${m.t}" x2="${m.l}" y2="${H - m.b}"/>
    <line class="axis" x1="${m.l}" y1="${H - m.b}" x2="${W - m.r}" y2="${H - m.b}"/>
    ${dots}
    <text class="tick" x="${W - m.r}" y="${H - 8}" text-anchor="end" style="display:none">km</text>
  </svg>`;
}

function renderTable(results, cur) {
  const body = $("resultsBody");
  const empty = $("empty");
  const table = $("resultsTable");

  if (!results.length) {
    body.innerHTML = "";
    table.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }
  table.classList.remove("hidden");
  empty.classList.add("hidden");

  body.innerHTML = results.map((r, i) => {
    const stopsClass = r.stops === 0 ? "" : r.stops === 1 ? " one" : " many";
    const stopsText = r.stops === 0 ? "直飞" : `${r.stops} 转`;
    const saving = r.saving_pct >= 4
      ? `<span class="tag best">省 ${Math.round(r.saving_pct)}%</span>`
      : "";
    const bestTag = r.deal_score >= 85 ? `<span class="tag hot">超值</span>` : "";
    const links = r.booking_links || {};
    return `<tr>
      <td class="c-rank"><span class="rank">${i + 1}</span></td>
      <td class="c-dest">
        <div class="dest">
          <span class="cc">${esc(r.cc)}</span>
          <div class="names">
            <div class="city">${esc(r.city)}</div>
            <div class="meta"><span class="code">${esc(r.code)}</span> · ${esc(r.region)} ${saving}${bestTag}</div>
          </div>
        </div>
      </td>
      <td class="c-price"><div class="price"><span class="cur">${sym(cur)}</span>${money(r.price)}</div></td>
      <td class="c-dates"><div class="dates">${r.depart.slice(5)} → ${r.return.slice(5)}<span class="nights">${r.nights} 晚</span></div></td>
      <td class="c-air"><div class="air">${esc(r.airline || "—")}<span class="stops${stopsClass}">${stopsText}</span></div></td>
      <td class="c-dur"><div class="dur">${esc(r.duration_label)}<small>${money(r.distance_km)} km</small></div></td>
      <td class="c-score"><div class="score"><span class="track"><span class="fill" style="width:${r.deal_score}%"></span></span><span class="num">${r.deal_score}</span></div></td>
      <td class="c-links"><div class="links">
        ${links.google ? `<a class="link gf" href="${esc(links.google)}" target="_blank" rel="noopener noreferrer">Google</a>` : ""}
        ${links.trip ? `<a class="link" href="${esc(links.trip)}" target="_blank" rel="noopener noreferrer">Trip</a>` : ""}
      </div></td>
    </tr>`;
  }).join("");
}

/* ------------------------------------------------------------------ start */

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.payload) renderScatter(state.payload.results || [], state.payload.meta.currency);
  }, 180);
});

init();
