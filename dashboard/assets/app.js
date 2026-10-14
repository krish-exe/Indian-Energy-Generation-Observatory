/* India Energy Observatory dashboard. Static: reads data/*.json produced by `python -m observatory export`. */
"use strict";

const STATE = { m: null, ins: null, entities: null, catalog: null, charts: [], page: null };

/* ------------------------------------------------------------------ colour (validated palettes) */
const PAL = {
  light: {
    fuel: { WIND: "#2a78d6", SOLAR: "#eb6834", HYDRO: "#1baf7a", OTHER_RES: "#eda100", NUCLEAR: "#e87ba4",
            COAL: "#4a3aa7", LIGNITE: "#4a3aa7", GAS: "#e34948", STORAGE: "#898781" },
    group: { renewable: "#008300", nuclear: "#e87ba4", non_renewable: "#4a3aa7" },
    cause: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
    seq: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
  },
  dark: {
    fuel: { WIND: "#3987e5", SOLAR: "#d95926", HYDRO: "#199e70", OTHER_RES: "#c98500", NUCLEAR: "#d55181",
            COAL: "#9085e9", LIGNITE: "#9085e9", GAS: "#e66767", STORAGE: "#898781" },
    group: { renewable: "#008300", nuclear: "#d55181", non_renewable: "#9085e9" },
    cause: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"],
    seq: ["#104281", "#184f95", "#1c5cab", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"],
  },
};
const FUEL_LABEL = { WIND: "Wind", SOLAR: "Solar", HYDRO: "Hydro (large)", OTHER_RES: "Biomass & other RE",
  NUCLEAR: "Nuclear", COAL: "Coal & lignite", GAS: "Gas, naphtha & diesel", LIGNITE: "Lignite", STORAGE: "Storage discharge" };
const GROUP_LABEL = { renewable: "Renewable (incl. large hydro)", nuclear: "Nuclear", non_renewable: "Fossil (coal, lignite, gas)" };
const CAUSES = ["planned", "forced_equipment", "fuel_supply", "commercial", "long_term_or_retired", "regulatory_or_other"];
const CAUSE_LABEL = { planned: "Planned maintenance", forced_equipment: "Equipment failure", fuel_supply: "Fuel supply",
  commercial: "Commercial (no schedule)", long_term_or_retired: "Long-term / retiring", regulatory_or_other: "Regulatory & other" };
const MIX = ["WIND", "SOLAR", "HYDRO", "OTHER_RES", "NUCLEAR", "COAL", "GAS"];

function isDark() {
  const t = document.documentElement.dataset.theme;
  if (t === "dark") return true;
  if (t === "light") return false;
  return matchMedia("(prefers-color-scheme: dark)").matches;
}
const pal = () => PAL[isDark() ? "dark" : "light"];
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

/* ------------------------------------------------------------------ formatting */
const nf = (d = 0) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v) ? "–" : nf(d).format(v));
const monthName = (m) => new Date(m + "-01T00:00:00").toLocaleString("en-GB", { month: "short", year: "2-digit" })
  + (STATE.m && (STATE.m.window[0].startsWith(m) && !STATE.m.window[0].endsWith("-01") || STATE.m.window[1].startsWith(m)) ? "*" : "");
const dateName = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const sum = (a) => a.reduce((s, v) => s + (v || 0), 0);

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : document.createTextNode(k));
  return e;
}
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

/* ------------------------------------------------------------------ downloads */
function slug(s) { return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, ""); }
function downloadRows(rows, columns, name, type) {
  const header = columns.map((c) => c.label);
  const body = rows.map((r) => columns.map((c) => r[c.key] ?? ""));
  const base = `india-energy-observatory_${slug(name)}`;
  if (type === "xlsx") {
    if (!window.XLSX) { toast("Excel library still loading - try again"); return; }
    const ws = XLSX.utils.aoa_to_sheet([header, ...body]);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "data");
    const meta = XLSX.utils.aoa_to_sheet([["View", name], ["Period", STATE.m.window.join(" to ")],
      ["Sources", "Central Electricity Authority (npp.gov.in, gen-re.cea.gov.in); Grid Controller of India (grid-india.in)"],
      ["Full tables", "Data & downloads page of the dashboard"]]);
    XLSX.utils.book_append_sheet(wb, meta, "about");
    XLSX.writeFile(wb, base + ".xlsx");
  } else {
    const esc = (v) => { const s = String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = [header, ...body].map((r) => r.map(esc).join(",")).join("\n");
    const a = el("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: base + ".csv" });
    document.body.append(a); a.click(); a.remove();
  }
}

/* ------------------------------------------------------------------ chart chrome */
function baseOption() {
  const text2 = css("--text-secondary"), muted = css("--text-muted"), grid = css("--grid"), axis = css("--axis");
  return {
    animationDuration: 300,
    textStyle: { fontFamily: css("--font") || "system-ui", color: text2 },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    legend: { top: 0, left: 0, type: "scroll", icon: "roundRect", itemWidth: 12, itemHeight: 8,
              textStyle: { color: text2, fontSize: 12 }, pageTextStyle: { color: text2 } },
    tooltip: { backgroundColor: css("--surface-1"), borderColor: css("--border"), borderWidth: 1,
               textStyle: { color: css("--text-primary"), fontSize: 12 }, confine: true,
               extraCssText: "box-shadow:0 4px 16px rgba(0,0,0,.12);border-radius:8px;" },
    xAxisBase: { axisLine: { lineStyle: { color: axis } }, axisTick: { show: false },
                 axisLabel: { color: muted, fontSize: 11 }, splitLine: { show: false } },
    yAxisBase: { axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: muted, fontSize: 11 },
                 splitLine: { lineStyle: { color: grid, width: 1 } }, nameTextStyle: { color: muted, fontSize: 11 } },
  };
}
function axes(o, x, y) {
  return { ...o, xAxis: { ...o.xAxisBase, ...x }, yAxis: { ...o.yAxisBase, ...y }, xAxisBase: undefined, yAxisBase: undefined };
}
function axisTooltip(unit, d = 0) {
  return {
    trigger: "axis", axisPointer: { type: "line", lineStyle: { color: css("--axis") } },
    valueFormatter: (v) => (v === null || v === undefined ? "–" : `${fmt(v, d)} ${unit}`),
  };
}
const barStyle = (color) => ({ color, borderRadius: [4, 4, 0, 0] });

/* ------------------------------------------------------------------ cards */
function card(parent, cfg) {
  const chartDiv = el("div", { class: `chart ${cfg.size || ""}`, role: "img", "aria-label": cfg.title });
  const tableWrap = el("div", { class: "table-wrap hidden" });
  const cols = cfg.columns;
  const tableBtn = el("button", { class: "btn", type: "button", text: "Table", "aria-expanded": "false" });
  const c = el("section", { class: `card span-${cfg.span || 6}` },
    el("h2", { text: cfg.title }), el("div", { class: "sub", text: cfg.sub || "" }),
    cfg.controls || null, chartDiv, tableWrap,
    el("div", { class: "card-actions" },
      tableBtn,
      el("button", { class: "btn", type: "button", text: "Download Excel",
        onclick: () => downloadRows(cfg.rows(), cols, cfg.title, "xlsx") }),
      el("button", { class: "btn", type: "button", text: "CSV",
        onclick: () => downloadRows(cfg.rows(), cols, cfg.title, "csv") }),
      el("span", { class: "spacer" }), el("span", { class: "src", text: cfg.source || "" })));
  tableBtn.addEventListener("click", () => {
    const show = tableWrap.classList.contains("hidden");
    tableWrap.classList.toggle("hidden", !show);
    tableBtn.setAttribute("aria-expanded", String(show));
    if (show) tableWrap.replaceChildren(renderTable(cfg.rows(), cols));
  });
  parent.append(c);
  const entry = { div: chartDiv, cfg, chart: null };
  entry.draw = () => {
    if (entry.chart) entry.chart.dispose();
    entry.chart = echarts.init(chartDiv, null, { renderer: "canvas" });
    entry.chart.setOption(cfg.option(), true);
    if (!tableWrap.classList.contains("hidden")) tableWrap.replaceChildren(renderTable(cfg.rows(), cols));
  };
  STATE.charts.push(entry);
  entry.draw();
  return entry;
}
function renderTable(rows, cols, limit = 2000) {
  const t = el("table");
  t.append(el("thead", {}, el("tr", {}, cols.map((c) => el("th", { class: c.num ? "num" : "", text: c.label })))));
  const tb = el("tbody");
  for (const r of rows.slice(0, limit)) {
    tb.append(el("tr", {}, cols.map((c) => el("td", { class: c.num ? "num" : "",
      text: c.num ? fmt(r[c.key], c.d ?? 1) : (r[c.key] ?? "") }))));
  }
  t.append(tb);
  return t;
}
function findings(parent, page) {
  const items = (STATE.ins && STATE.ins[page]) || [];
  if (!items.length) return;
  const ul = el("ul");
  for (const f of items) {
    ul.append(el("li", {}, f.text, el("span", { class: "meta",
      text: `${f.source} · ${f.period}${f.caveat ? " · " + f.caveat : ""}` })));
  }
  parent.append(el("section", { class: "findings", "aria-label": "Findings" }, el("h2", { text: "What the data shows" }), ul));
}
function head(parent, title, text) {
  parent.append(el("div", { class: "page-head" }, el("h1", { text: title }), el("p", { text })));
}
function tile(label, value, note, hero = false) {
  return el("div", { class: `tile${hero ? " hero" : ""}` }, el("div", { class: "label", text: label }),
    el("div", { class: "value", text: value }), note ? el("div", { class: "note", text: note }) : null);
}
function zip(obj, keys) { // columnar -> rows
  const n = obj[keys[0]].length; const out = [];
  for (let i = 0; i < n; i++) { const r = {}; for (const k of keys) r[k] = obj[k][i]; out.push(r); }
  return out;
}

/* ------------------------------------------------------------------ pages */
function pageOverview(root) {
  const m = STATE.m, md = m.mix_monthly;
  const tot = sum(md.TOTAL), ren = sum(md.renewable), nuc = sum(md.nuclear);
  const dd = m.demand_daily;
  const pk = dd.max_demand_met_mw.indexOf(Math.max(...dd.max_demand_met_mw.filter((v) => v !== null)));
  head(root, "India's electricity, one year of official reports",
    "How much electricity India generated from each source, how renewable and fossil sources compare, and how often generating units were out. Built entirely from Central Electricity Authority and Grid-India daily reports.");
  root.append(el("div", { class: "tiles" },
    tile("Renewable share of generation", `${fmt(ren / tot * 100, 1)}%`, "incl. large hydro · gross generation", true),
    tile("Non-fossil share", `${fmt((ren + nuc) / tot * 100, 1)}%`, "renewable + nuclear"),
    tile("Total generation", `${fmt(tot / 1000, 0)} TWh`, `${m.window[0]} to ${m.window[1]}`),
    tile("Peak demand met", `${fmt(dd.max_demand_met_mw[pk] / 1000, 1)} GW`, dateName(dd.date[pk])),
    tile("Avg. generation capacity out", `${fmt(sum(dd.gen_outage_total_mw) / dd.gen_outage_total_mw.filter((v) => v !== null).length / 1000, 1)} GW`, "all sectors, Grid-India"),
    tile("Unmet demand", `${fmt(sum(dd.energy_shortage_mu), 0)} MU`, `${fmt(sum(dd.energy_shortage_mu) / (sum(dd.energy_met_mu) + sum(dd.energy_shortage_mu)) * 100, 2)}% of demand`)));
  findings(root, "overview");
  const g = el("div", { class: "grid" }); root.append(g);
  mixCard(g, 12);
  groupShareCard(g, 12, "monthly");
}

function mixCard(g, span) {
  const m = STATE.m;
  let mode = "monthly";
  const seg = el("div", { class: "seg", role: "group", "aria-label": "Resolution" });
  const entry = { ref: null };
  for (const k of ["daily", "monthly"]) {
    seg.append(el("button", { type: "button", "aria-pressed": String(k === mode), text: k[0].toUpperCase() + k.slice(1),
      onclick: (e) => { mode = k; seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.target))); entry.ref.draw(); } }));
  }
  const data = () => (mode === "daily" ? m.mix_daily : m.mix_monthly);
  const xKey = () => (mode === "daily" ? "date" : "month");
  entry.ref = card(g, {
    span, size: "tall", title: "Generation by source", controls: el("div", { class: "controls" }, seg),
    sub: "Gross generation, million units (GWh). All-India, Grid-India daily PSP reports. * partial month at the edges of the window.",
    source: "Grid-India PSP",
    columns: [{ key: "period", label: "Period" }, ...MIX.map((k) => ({ key: k, label: FUEL_LABEL[k] + " (MU)", num: true })),
      { key: "TOTAL", label: "Total (MU)", num: true }, { key: "re_share", label: "Renewable share %", num: true }],
    rows: () => { const d = data(); return d[xKey()].map((p, i) => ({ period: p, ...Object.fromEntries(MIX.map((k) => [k, d[k][i]])), TOTAL: d.TOTAL[i], re_share: d.re_share[i] })); },
    option: () => {
      const o = baseOption(), d = data(), P = pal();
      const bars = mode === "monthly";
      return axes({ ...o, tooltip: { ...o.tooltip, ...axisTooltip("MU") }, legend: { ...o.legend, data: MIX.map((k) => FUEL_LABEL[k]) },
        series: MIX.map((k) => bars
          ? { name: FUEL_LABEL[k], type: "bar", stack: "s", data: d[k], barMaxWidth: 24,
              itemStyle: { color: P.fuel[k], borderColor: css("--surface-1"), borderWidth: 1 } }
          : { name: FUEL_LABEL[k], type: "line", stack: "s", data: d[k], symbol: "none", lineStyle: { width: 0 },
              areaStyle: { color: P.fuel[k], opacity: 0.92 }, itemStyle: { color: P.fuel[k] } }),
      }, { type: "category", data: d[xKey()].map((p) => (bars ? monthName(p) : p)), boundaryGap: bars },
      { type: "value", name: "MU", axisLabel: { color: css("--text-muted"), formatter: (v) => fmt(v) } });
    },
  });
}

function groupShareCard(g, span, mode = "daily") {
  const m = STATE.m;
  const d = mode === "daily" ? m.mix_daily : m.mix_monthly;
  const x = mode === "daily" ? d.date : d.month;
  const keys = ["renewable", "nuclear", "non_renewable"];
  const share = (k) => d[k].map((v, i) => (v / d.TOTAL[i]) * 100);
  card(g, {
    span, title: "Renewable vs nuclear vs fossil share", size: mode === "daily" ? "" : "short",
    sub: `Share of gross generation, % (${mode}). Large hydro counted as renewable.`, source: "Grid-India PSP",
    columns: [{ key: "p", label: "Period" }, ...keys.map((k) => ({ key: k, label: GROUP_LABEL[k] + " %", num: true }))],
    rows: () => x.map((p, i) => ({ p, ...Object.fromEntries(keys.map((k) => [k, share(k)[i]])) })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, tooltip: { ...o.tooltip, ...axisTooltip("%", 1) },
        series: keys.map((k) => mode === "daily"
          ? { name: GROUP_LABEL[k], type: "line", stack: "g", data: share(k), symbol: "none", lineStyle: { width: 0 },
              areaStyle: { color: P.group[k], opacity: 0.92 }, itemStyle: { color: P.group[k] } }
          : { name: GROUP_LABEL[k], type: "bar", stack: "g", data: share(k), barMaxWidth: 24,
              itemStyle: { color: P.group[k], borderColor: css("--surface-1"), borderWidth: 1 } }) },
      { type: "category", data: mode === "daily" ? x : x.map(monthName), boundaryGap: mode !== "daily" },
      { type: "value", max: 100, axisLabel: { color: css("--text-muted"), formatter: "{value}%" } });
    },
  });
}

function pageMix(root) {
  const m = STATE.m;
  head(root, "Sustainable vs unsustainable generation",
    "Renewable (solar, wind, large hydro, biomass), nuclear (low-carbon but not renewable) and fossil (coal, lignite, gas) generation compared over time, by region and through the day.");
  findings(root, "mix");
  const g = el("div", { class: "grid" }); root.append(g);
  groupShareCard(g, 12, "daily");

  const rg = m.region_mix;
  card(g, {
    span: 6, title: "Renewable and non-fossil share by region", sub: "% of the region's gross generation over the year",
    source: "Grid-India PSP",
    columns: [{ key: "region", label: "Region" }, { key: "re_share", label: "Renewable %", num: true },
      { key: "non_fossil_share", label: "Non-fossil %", num: true }, { key: "TOTAL", label: "Total MU", num: true, d: 0 }],
    rows: () => zip(rg, ["region", "re_share", "non_fossil_share", "TOTAL"]),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, tooltip: { ...o.tooltip, trigger: "item", valueFormatter: (v) => `${fmt(v, 1)}%` },
        series: [
          { name: "Renewable", type: "bar", data: rg.re_share, barMaxWidth: 24, itemStyle: barStyle(P.group.renewable),
            label: { show: true, position: "top", color: css("--text-secondary"), fontSize: 11, formatter: (p) => `${fmt(p.value, 0)}%` } },
          { name: "Non-fossil (incl. nuclear)", type: "bar", data: rg.non_fossil_share, barMaxWidth: 24, itemStyle: barStyle(P.group.nuclear) }] },
      { type: "category", data: rg.region, axisLabel: { color: css("--text-muted"), fontSize: 11, interval: 0 } }, { type: "value", axisLabel: { color: css("--text-muted"), formatter: "{value}%" } });
    },
  });

  const hm = m.region_re_share_monthly;
  card(g, {
    span: 6, title: "Renewable share by region and month", sub: "% of gross generation; darker = higher share",
    source: "Grid-India PSP",
    columns: [{ key: "region", label: "Region" }, ...hm.months.map((mo, i) => ({ key: "m" + i, label: monthName(mo), num: true }))],
    rows: () => hm.regions.map((r, j) => ({ region: r, ...Object.fromEntries(hm.months.map((_, i) => ["m" + i, hm.values[j][i]])) })),
    option: () => {
      const o = baseOption(), P = pal();
      const data = [];
      const darkCell = (v) => (isDark() ? v < 55 : v >= 45);
      hm.regions.forEach((r, j) => hm.months.forEach((mo, i) => {
        const v = hm.values[j][i];
        data.push({ value: [i, j, v], label: { color: darkCell(v) ? "#ffffff" : "#0b0b0b" } });
      }));
      return { ...o, xAxisBase: undefined, yAxisBase: undefined, grid: { ...o.grid, bottom: 48 },
        tooltip: { ...o.tooltip, trigger: "item", formatter: (p) => `${hm.regions[p.value[1]]}, ${monthName(hm.months[p.value[0]])}<br><b>${fmt(p.value[2], 1)}%</b> renewable` },
        xAxis: { type: "category", data: hm.months.map(monthName), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: css("--text-muted"), fontSize: 11 } },
        yAxis: { type: "category", data: hm.regions, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: css("--text-muted"), fontSize: 11 } },
        visualMap: { min: 0, max: 100, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemWidth: 10,
          inRange: { color: P.seq }, textStyle: { color: css("--text-muted"), fontSize: 11 }, formatter: (v) => `${fmt(v)}%` },
        series: [{ type: "heatmap", data, itemStyle: { borderColor: css("--surface-1"), borderWidth: 2, borderRadius: 3 },
          label: { show: true, fontSize: 10, formatter: (p) => fmt(p.value[2], 0) } }] };
    },
  });

  // 15-minute profile
  const pr = m.profile_15min;
  if (pr) {
    const months = Object.keys(pr.months).sort();
    let sel = months[months.length - 1];
    const select = el("select", { "aria-label": "Month" }, months.map((mo) => el("option", { value: mo, text: monthName(mo) })));
    select.value = sel;
    const map = [["solar_mw", "SOLAR"], ["wind_mw", "WIND"], ["hydro_mw", "HYDRO"], ["others_mw", "OTHER_RES"],
      ["nuclear_mw", "NUCLEAR"], ["thermal_mw", "COAL"], ["gas_mw", "GAS"], ["storage_gen_mw", "STORAGE"]].filter(([c]) => pr.cols.includes(c));
    const label = (c, k) => (c === "thermal_mw" ? "Thermal (coal & lignite)" : c === "others_mw" ? "Others" : FUEL_LABEL[k]);
    const ref = card(g, {
      span: 12, size: "tall", title: "A typical day in the grid",
      controls: el("div", { class: "controls" }, el("label", { text: "Month" }), select),
      sub: "Average all-India generation by source for each 15-minute slot, MW. Solar fills the middle of the day; coal and hydro carry the evening peak.",
      source: "Grid-India 15-min SCADA",
      columns: [{ key: "time", label: "Time" }, ...map.map(([c, k]) => ({ key: c, label: label(c, k) + " (MW)", num: true, d: 0 })),
        { key: "demand_met_mw", label: "Demand met (MW)", num: true, d: 0 }],
      rows: () => pr.times.map((t, i) => ({ time: t, ...Object.fromEntries([...map.map(([c]) => c), "demand_met_mw"].map((c) => [c, pr.months[sel][c] ? pr.months[sel][c][i] : null])) })),
      option: () => {
        const o = baseOption(), P = pal(), d = pr.months[sel];
        return axes({ ...o, tooltip: { ...o.tooltip, ...axisTooltip("MW") },
          series: [...map.map(([c, k]) => ({ name: label(c, k), type: "line", stack: "p", data: d[c], symbol: "none", lineStyle: { width: 0 },
            areaStyle: { color: P.fuel[k], opacity: 0.92 }, itemStyle: { color: P.fuel[k] } })),
            { name: "Demand met", type: "line", data: d.demand_met_mw, symbol: "none", lineStyle: { width: 2, color: css("--text-primary") }, itemStyle: { color: css("--text-primary") } }] },
        { type: "category", data: pr.times, boundaryGap: false }, { type: "value", name: "MW", axisLabel: { color: css("--text-muted"), formatter: (v) => fmt(v / 1000) + "k" } });
      },
    });
    select.addEventListener("change", () => { sel = select.value; ref.draw(); });
  }

  const pv = m.program_vs_actual;
  const pfuels = ["COAL", "GAS", "NUCLEAR", "HYDRO"];
  card(g, {
    span: 12, title: "Actual generation vs CEA's programme", sub: "Monthly deviation from planned generation, % (above 0 = generated more than planned)",
    source: "CEA DGR Sub-report 17",
    columns: [{ key: "month", label: "Month" }, ...Object.keys(pv.series).map((k) => ({ key: k, label: k + " deviation %", num: true }))],
    rows: () => pv.months.map((mo, i) => ({ month: mo, ...Object.fromEntries(Object.keys(pv.series).map((k) => [k, pv.series[k][i]])) })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, tooltip: { ...o.tooltip, ...axisTooltip("%", 1) },
        series: pfuels.map((k) => ({ name: k === "COAL" ? "Coal" : FUEL_LABEL[k], type: "line", data: pv.series[k], symbolSize: 8,
          lineStyle: { width: 2, color: P.fuel[k] }, itemStyle: { color: P.fuel[k], borderColor: css("--surface-1"), borderWidth: 2 } })) },
      { type: "category", data: pv.months.map(monthName) }, { type: "value", axisLabel: { color: css("--text-muted"), formatter: "{value}%" } });
    },
  });
}

function pageRenewables(root) {
  const m = STATE.m;
  head(root, "Comparing sustainable sources",
    "Solar, wind, large hydro and biomass compared on output, capacity factor, seasonality and day-to-day variability. Variable output is the nature of the resource, not a reliability failure.");
  findings(root, "renewables");
  const g = el("div", { class: "grid" }); root.append(g);
  const mm = m.mix_monthly;
  const reKeys = ["WIND", "SOLAR", "HYDRO", "OTHER_RES"];
  card(g, {
    span: 7, title: "Monthly generation by renewable source", sub: "Gross generation, MU", source: "Grid-India PSP",
    columns: [{ key: "month", label: "Month" }, ...reKeys.map((k) => ({ key: k, label: FUEL_LABEL[k] + " (MU)", num: true, d: 0 }))],
    rows: () => zip(mm, ["month", ...reKeys]),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, tooltip: { ...o.tooltip, ...axisTooltip("MU") },
        series: reKeys.map((k) => ({ name: FUEL_LABEL[k], type: "bar", data: mm[k], barMaxWidth: 14, itemStyle: barStyle(P.fuel[k]) })) },
      { type: "category", data: mm.month.map(monthName) }, { type: "value", axisLabel: { color: css("--text-muted"), formatter: (v) => fmt(v) } });
    },
  });
  const cw = m.cf_window;
  const cfKeys = ["SOLAR", "WIND", "HYDRO", "NUCLEAR", "COAL", "GAS"].filter((k) => cw[k] !== undefined);
  card(g, {
    span: 5, title: "Capacity factor over the year", sub: "Energy produced ÷ what the installed capacity could produce running 24/7, %",
    source: "CEA DGR + CEA RE",
    columns: [{ key: "fuel", label: "Source" }, { key: "cf", label: "Capacity factor %", num: true }],
    rows: () => cfKeys.map((k) => ({ fuel: FUEL_LABEL[k] || k, cf: cw[k] })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, grid: { ...o.grid, top: 8 }, tooltip: { ...o.tooltip, trigger: "item", valueFormatter: (v) => `${fmt(v, 1)}%` },
        series: [{ type: "bar", barMaxWidth: 24, data: cfKeys.map((k) => ({ value: cw[k], itemStyle: { color: P.fuel[k], borderRadius: [0, 4, 4, 0] } })),
          label: { show: true, position: "right", color: css("--text-secondary"), fontSize: 11, formatter: (p) => `${fmt(p.value, 1)}%` } }] },
      { type: "value", axisLabel: { color: css("--text-muted"), formatter: "{value}%" }, splitLine: { lineStyle: { color: css("--grid") } } },
      { type: "category", data: cfKeys.map((k) => FUEL_LABEL[k]), inverse: true, splitLine: { show: false } });
    },
  });
  const cm = m.cf_monthly;
  const cmKeys = ["SOLAR", "WIND", "HYDRO", "NUCLEAR", "COAL"];
  card(g, {
    span: 7, title: "Capacity factor by month", sub: "% - the seasons: monsoon lifts wind and hydro, cloud cover lowers solar",
    source: "CEA DGR + CEA RE",
    columns: [{ key: "month", label: "Month" }, ...cmKeys.map((k) => ({ key: k, label: FUEL_LABEL[k] + " %", num: true }))],
    rows: () => cm.months.map((mo, i) => ({ month: mo, ...Object.fromEntries(cmKeys.map((k) => [k, cm.series[k][i]])) })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, tooltip: { ...o.tooltip, ...axisTooltip("%", 1) },
        series: cmKeys.map((k) => ({ name: FUEL_LABEL[k], type: "line", data: cm.series[k], symbolSize: 8,
          lineStyle: { width: 2, color: P.fuel[k] }, itemStyle: { color: P.fuel[k], borderColor: css("--surface-1"), borderWidth: 2 },
          endLabel: { show: false } })) },
      { type: "category", data: cm.months.map(monthName) }, { type: "value", axisLabel: { color: css("--text-muted"), formatter: "{value}%" } });
    },
  });
  const vw = m.variability_window, dd = m.day_to_day_change_median_pct;
  const vKeys = ["SOLAR", "WIND", "HYDRO", "NUCLEAR", "COAL", "GAS"];
  card(g, {
    span: 5, title: "How much output swings day to day", sub: "Coefficient of variation of daily all-India output over the year, %",
    source: "Grid-India PSP",
    columns: [{ key: "fuel", label: "Source" }, { key: "cv", label: "Coefficient of variation %", num: true }, { key: "dod", label: "Median day-to-day change %", num: true }],
    rows: () => vKeys.map((k) => ({ fuel: FUEL_LABEL[k], cv: vw[k], dod: dd[k] })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, grid: { ...o.grid, top: 8 }, tooltip: { ...o.tooltip, trigger: "item", valueFormatter: (v) => `${fmt(v, 1)}%` },
        series: [{ type: "bar", barMaxWidth: 24, data: vKeys.map((k) => ({ value: vw[k], itemStyle: { color: P.fuel[k], borderRadius: [0, 4, 4, 0] } })),
          label: { show: true, position: "right", color: css("--text-secondary"), fontSize: 11, formatter: (p) => `${fmt(p.value, 1)}%` } }] },
      { type: "value", axisLabel: { color: css("--text-muted"), formatter: "{value}%" }, splitLine: { lineStyle: { color: css("--grid") } } },
      { type: "category", data: vKeys.map((k) => FUEL_LABEL[k]), inverse: true, splitLine: { show: false } });
    },
  });
  const md = m.mix_daily;
  card(g, {
    span: 6, title: "Do wind and solar offset each other?", sub: `Daily all-India wind vs solar generation, MU (r = ${fmt(m.complementarity.corr_wind_solar_daily, 2)})`,
    source: "Grid-India PSP",
    columns: [{ key: "date", label: "Date" }, { key: "WIND", label: "Wind (MU)", num: true }, { key: "SOLAR", label: "Solar (MU)", num: true }],
    rows: () => zip(md, ["date", "WIND", "SOLAR"]),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, grid: { ...o.grid, top: 16 }, tooltip: { ...o.tooltip, trigger: "item",
          formatter: (p) => `${p.data[2]}<br>Wind <b>${fmt(p.data[0], 1)} MU</b><br>Solar <b>${fmt(p.data[1], 1)} MU</b>` },
        series: [{ type: "scatter", symbolSize: 8, data: md.date.map((d, i) => [md.WIND[i], md.SOLAR[i], d]),
          itemStyle: { color: P.fuel.WIND, opacity: 0.75, borderColor: css("--surface-1"), borderWidth: 1 } }] },
      { type: "value", name: "Wind MU", nameLocation: "middle", nameGap: 26, axisLabel: { color: css("--text-muted") }, splitLine: { lineStyle: { color: css("--grid") } } },
      { type: "value", name: "Solar MU" });
    },
  });
  const sr = m.state_re;
  const n = Math.min(15, sr.state.length);
  const sKeys = ["SOLAR", "WIND", "HYDRO", "OTHER_RES"];
  card(g, {
    span: 6, size: "tall", title: "Where renewable electricity is generated", sub: "Top states by renewable generation over the year, MU (hybrid plants folded into solar)",
    source: "CEA RE + CEA DGR (hydro)",
    columns: [{ key: "state", label: "State" }, ...["SOLAR", "WIND", "HYBRID", "OTHER_RES", "HYDRO", "TOTAL"].map((k) => ({ key: k, label: (FUEL_LABEL[k] || k) + " (MU)", num: true, d: 0 }))],
    rows: () => zip(sr, ["state", "SOLAR", "WIND", "HYBRID", "OTHER_RES", "HYDRO", "TOTAL"]),
    option: () => {
      const o = baseOption(), P = pal();
      const states = sr.state.slice(0, n);
      const val = (k, i) => (k === "SOLAR" ? (sr.SOLAR[i] || 0) + (sr.HYBRID[i] || 0) : sr[k][i]);
      return axes({ ...o, tooltip: { ...o.tooltip, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => `${fmt(v)} MU` },
        series: sKeys.map((k) => ({ name: FUEL_LABEL[k], type: "bar", stack: "r", barMaxWidth: 18,
          data: states.map((_, i) => val(k, i)), itemStyle: { color: P.fuel[k], borderColor: css("--surface-1"), borderWidth: 1 } })) },
      { type: "value", axisLabel: { color: css("--text-muted"), formatter: (v) => fmt(v / 1000) + "k" }, splitLine: { lineStyle: { color: css("--grid") } } },
      { type: "category", data: states, inverse: true, splitLine: { show: false } });
    },
  });
  for (const lg of m.re_league) {
    const rows = zip(lg.top, ["entity_name", "state", "cap", "cf", "days"]);
    const sec = el("section", { class: "card span-6" }, el("h2", { text: `Best-performing ${lg.fuel.toLowerCase()} stations` }),
      el("div", { class: "sub", text: `Inter-state (ISGS) stations ≥ 50 MW, ranked by capacity factor. Median across ${lg.n} stations: ${fmt(lg.median_cf, 1)}%.` }));
    const cols = [{ key: "entity_name", label: "Station" }, { key: "state", label: "State" }, { key: "cap", label: "MW", num: true, d: 0 },
      { key: "cf", label: "Capacity factor %", num: true }, { key: "days", label: "Days reported", num: true, d: 0 }];
    const wrap = el("div", { class: "table-wrap" }, renderTable(rows, cols));
    sec.append(wrap, el("div", { class: "card-actions" },
      el("button", { class: "btn", type: "button", text: "Download Excel", onclick: () => downloadRows(rows, cols, `top ${lg.fuel} stations`, "xlsx") }),
      el("button", { class: "btn", type: "button", text: "CSV", onclick: () => downloadRows(rows, cols, `top ${lg.fuel} stations`, "csv") }),
      el("span", { class: "spacer" }), el("span", { class: "src", text: "CEA RE (ISGS sheet)" })));
    g.append(sec);
  }
}

function pageOutages(root) {
  const m = STATE.m;
  head(root, "Where and why generating capacity goes offline",
    "Unavailable capacity for every source: solar and wind from Grid-India's renewable reports, and coal, lignite, gas, nuclear and large hydro from CEA's unit-level outage reports, with the reasons CEA gives.");
  root.append(el("p", { class: "note-box", text: "No official source lists outages of individual solar or wind units. The solar & wind section uses the three closest official measures: capacity not available each day (Grid-India REMC), grid events that took plants offline (Grid-India monthly reports), and days a solar station reported zero output (derived from CEA). A generating-unit outage is also not a consumer power cut: other plants and imports usually cover the gap." }));
  findings(root, "outages");
  const g = el("div", { class: "grid" }); root.append(g);
  solarWindOutages(g);
  g.append(el("div", { class: "span-12 section-head" }, el("h2", { text: "Coal, lignite, gas, nuclear and hydro" }),
    el("p", { text: "Unit-level outages reported by CEA." })));
  const ud = m.unavailable_daily;
  const oF = ["COAL", "LIGNITE", "GAS", "NUCLEAR", "HYDRO"];
  const lab = (k) => ({ COAL: "Coal", LIGNITE: "Lignite", GAS: "Gas, naphtha & diesel", NUCLEAR: "Nuclear", HYDRO: "Hydro (large)" })[k];
  card(g, {
    span: 12, title: "Share of capacity unavailable, by fuel", sub: "Daily capacity under outage ÷ monitored capacity, %",
    source: "CEA DGR Sub-report 2",
    columns: [{ key: "date", label: "Date" }, ...oF.map((k) => ({ key: k, label: lab(k) + " %", num: true })), ...oF.map((k) => ({ key: k + "_mw", label: lab(k) + " MW", num: true, d: 0 }))],
    rows: () => ud.dates.map((d, i) => ({ date: d, ...Object.fromEntries(oF.map((k) => [k, ud.pct[k][i]])), ...Object.fromEntries(oF.map((k) => [k + "_mw", ud.mw[k][i]])) })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, tooltip: { ...o.tooltip, ...axisTooltip("%", 1) },
        series: oF.map((k) => ({ name: lab(k), type: "line", data: ud.pct[k], symbol: "none",
          lineStyle: { width: 2, color: P.fuel[k], type: k === "LIGNITE" ? "dashed" : "solid" }, itemStyle: { color: P.fuel[k] } })) },
      { type: "category", data: ud.dates, boundaryGap: false }, { type: "value", axisLabel: { color: css("--text-muted"), formatter: "{value}%" } });
    },
  });
  const oc = m.outage_cause_daily;
  card(g, {
    span: 12, title: "Why coal, lignite and nuclear units were out", sub: "Daily MW under outage by cause (classified from CEA's reported reason)",
    source: "CEA DGR Sub-report 10",
    columns: [{ key: "date", label: "Date" }, ...CAUSES.map((c) => ({ key: c, label: CAUSE_LABEL[c] + " (MW)", num: true, d: 0 }))],
    rows: () => oc.dates.map((d, i) => ({ date: d, ...Object.fromEntries(CAUSES.map((c) => [c, oc.series[c][i]])) })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, tooltip: { ...o.tooltip, ...axisTooltip("MW") },
        series: CAUSES.map((c, i) => ({ name: CAUSE_LABEL[c], type: "line", stack: "c", data: oc.series[c], symbol: "none", lineStyle: { width: 0 },
          areaStyle: { color: P.cause[i], opacity: 0.92 }, itemStyle: { color: P.cause[i] } })) },
      { type: "category", data: oc.dates, boundaryGap: false }, { type: "value", axisLabel: { color: css("--text-muted"), formatter: (v) => fmt(v / 1000) + "k" } });
    },
  });
  const ur = m.unavailable_by_region;
  card(g, {
    span: 5, title: "Unavailable capacity by region", sub: "Average MW out per day (all conventional fuels)", source: "CEA DGR Sub-report 2",
    columns: [{ key: "region", label: "Region" }, { key: "avg_mw", label: "Average MW out", num: true, d: 0 }, { key: "pct", label: "% of capacity", num: true }],
    rows: () => zip(ur, ["regions", "avg_mw", "pct"]).map((r) => ({ region: r.regions, avg_mw: r.avg_mw, pct: r.pct })),
    option: () => {
      const o = baseOption();
      return axes({ ...o, grid: { ...o.grid, top: 8 }, tooltip: { ...o.tooltip, trigger: "item", formatter: (p) => `${p.name}<br><b>${fmt(p.value)} MW</b> (${fmt(ur.pct[p.dataIndex], 1)}% of capacity)` },
        series: [{ type: "bar", barMaxWidth: 24, data: ur.avg_mw, itemStyle: { color: pal().fuel.COAL, borderRadius: [4, 4, 0, 0] },
          label: { show: true, position: "top", color: css("--text-secondary"), fontSize: 11, formatter: (p) => `${fmt(ur.pct[p.dataIndex], 0)}%` } }] },
      { type: "category", data: ur.regions, axisLabel: { color: css("--text-muted"), fontSize: 11, interval: 0 } }, { type: "value", axisLabel: { color: css("--text-muted"), formatter: (v) => fmt(v / 1000) + "k" } });
    },
  });
  const ts = m.top_forced_stations;
  card(g, {
    span: 7, size: "tall", title: "Stations losing the most capacity to equipment failures", sub: "MW-days under forced outage (sum of daily MW out)",
    source: "CEA DGR Sub-report 10",
    columns: [{ key: "station", label: "Station" }, { key: "state", label: "State" }, { key: "mw_days", label: "MW-days", num: true, d: 0 }, { key: "units", label: "Units affected", num: true, d: 0 }],
    rows: () => zip(ts, ["station", "state", "mw_days", "units"]),
    option: () => {
      const o = baseOption();
      return axes({ ...o, grid: { ...o.grid, top: 8 }, tooltip: { ...o.tooltip, trigger: "item", formatter: (p) => `${p.name} (${ts.state[p.dataIndex]})<br><b>${fmt(p.value)} MW-days</b>` },
        series: [{ type: "bar", barMaxWidth: 18, data: ts.mw_days, itemStyle: { color: pal().cause[1], borderRadius: [0, 4, 4, 0] } }] },
      { type: "value", axisLabel: { color: css("--text-muted"), formatter: (v) => fmt(v / 1000) + "k" }, splitLine: { lineStyle: { color: css("--grid") } } },
      { type: "category", data: ts.station, inverse: true, splitLine: { show: false }, axisLabel: { color: css("--text-muted"), fontSize: 11, width: 170, overflow: "truncate" } });
    },
  });
  const dh = m.duration_hist;
  card(g, {
    span: 6, title: "How long outages last", sub: `Outages that started and ended in the window with a reported return time (n = ${fmt(dh.n_observed)}). ${fmt(dh.n_inferred)} ended without a reported time; ${fmt(dh.n_ongoing)} are still out.`,
    source: "CEA DGR Sub-report 10",
    columns: [{ key: "bin", label: "Duration" }, { key: "planned", label: "Planned", num: true, d: 0 }, { key: "forced_equipment", label: "Equipment failure", num: true, d: 0 }],
    rows: () => dh.bins.map((b, i) => ({ bin: b, planned: dh.series.planned[i], forced_equipment: dh.series.forced_equipment[i] })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, tooltip: { ...o.tooltip, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => `${fmt(v)} outages` },
        series: [["planned", 0], ["forced_equipment", 1]].map(([c, i]) => ({ name: CAUSE_LABEL[c], type: "bar", data: dh.series[c], barMaxWidth: 20, itemStyle: barStyle(P.cause[i]) })) },
      { type: "category", data: dh.bins }, { type: "value" });
    },
  });
  const em = m.events_monthly;
  card(g, {
    span: 6, title: "New outages each month, by cause", sub: "Number of unit outages that started in the month", source: "CEA DGR Sub-report 10",
    columns: [{ key: "month", label: "Month" }, ...CAUSES.map((c) => ({ key: c, label: CAUSE_LABEL[c], num: true, d: 0 }))],
    rows: () => em.months.map((mo, i) => ({ month: mo, ...Object.fromEntries(CAUSES.map((c) => [c, em.series[c][i]])) })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, tooltip: { ...o.tooltip, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => `${fmt(v)}` },
        series: CAUSES.map((c, i) => ({ name: CAUSE_LABEL[c], type: "bar", stack: "e", data: em.series[c], barMaxWidth: 24,
          itemStyle: { color: P.cause[i], borderColor: css("--surface-1"), borderWidth: 1 } })) },
      { type: "category", data: em.months.map(monthName) }, { type: "value" });
    },
  });
  const tr = m.top_reasons;
  card(g, {
    span: 6, size: "tall", title: "Most common causes of equipment failures", sub: "Outage events started in the window, by reported reason", source: "CEA DGR Sub-report 10",
    columns: [{ key: "reason_norm", label: "Reason" }, { key: "events", label: "Events", num: true, d: 0 }, { key: "med_h", label: "Median hours (reported returns)", num: true }],
    rows: () => zip(tr, ["reason_norm", "events", "med_h"]),
    option: () => {
      const o = baseOption();
      return axes({ ...o, grid: { ...o.grid, top: 8 }, tooltip: { ...o.tooltip, trigger: "item", formatter: (p) => `${p.name}<br><b>${fmt(p.value)} events</b>` },
        series: [{ type: "bar", barMaxWidth: 18, data: tr.events, itemStyle: { color: pal().cause[1], borderRadius: [0, 4, 4, 0] } }] },
      { type: "value", splitLine: { lineStyle: { color: css("--grid") } } },
      { type: "category", data: tr.reason_norm.map((s) => s.toLowerCase()), inverse: true, splitLine: { show: false }, axisLabel: { color: css("--text-muted"), fontSize: 11, width: 200, overflow: "truncate" } });
    },
  });
  const cs = m.coal_stock_vs_fuel_outage;
  card(g, {
    span: 6, size: "short", title: "Coal stock at power stations", sub: "Capacity-weighted average stock, days of consumption", source: "CEA DGR Sub-report 2",
    columns: [{ key: "month", label: "Month" }, { key: "stock_days", label: "Coal stock (days)", num: true }, { key: "fuel_outage_mw", label: "Avg MW out for fuel supply", num: true, d: 0 }],
    rows: () => zip({ month: cs.months, stock_days: cs.stock_days, fuel_outage_mw: cs.fuel_outage_mw }, ["month", "stock_days", "fuel_outage_mw"]),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, grid: { ...o.grid, top: 16 }, tooltip: { ...o.tooltip, ...axisTooltip("days", 1) },
        series: [{ name: "Coal stock", type: "line", data: cs.stock_days, symbolSize: 8, lineStyle: { width: 2, color: P.fuel.COAL }, itemStyle: { color: P.fuel.COAL, borderColor: css("--surface-1"), borderWidth: 2 },
          areaStyle: { color: P.fuel.COAL, opacity: 0.1 } }] },
      { type: "category", data: cs.months.map(monthName) }, { type: "value", axisLabel: { color: css("--text-muted"), formatter: "{value} d" } });
    },
  });
  card(g, {
    span: 6, size: "short", title: "Capacity out for fuel-supply reasons", sub: "Average MW per day in the month (coal, lignite, nuclear units)", source: "CEA DGR Sub-report 10",
    columns: [{ key: "month", label: "Month" }, { key: "fuel_outage_mw", label: "Avg MW out for fuel supply", num: true, d: 0 }],
    rows: () => cs.months.map((mo, i) => ({ month: mo, fuel_outage_mw: cs.fuel_outage_mw[i] })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, grid: { ...o.grid, top: 16 }, tooltip: { ...o.tooltip, trigger: "item", valueFormatter: (v) => `${fmt(v)} MW` },
        series: [{ type: "bar", data: cs.fuel_outage_mw, barMaxWidth: 24, itemStyle: barStyle(P.cause[2]) }] },
      { type: "category", data: cs.months.map(monthName) }, { type: "value" });
    },
  });
  tableCard(g, 6, "Units that fail again and again", "Units with the most equipment-failure outages that started in the window",
    zip(m.repeat_failures, ["station", "unit_no", "state", "events", "cap", "med_h"]),
    [{ key: "station", label: "Station" }, { key: "unit_no", label: "Unit" }, { key: "state", label: "State" }, { key: "events", label: "Failures", num: true, d: 0 },
      { key: "cap", label: "Unit MW", num: true, d: 0 }, { key: "med_h", label: "Median hours", num: true }], "CEA DGR Sub-report 10");
  tableCard(g, 6, `Stranded capacity: ${fmt(m.stranded.n)} units, ${fmt(m.stranded.mw)} MW`, "Out for more than a year before the window and still out at its end",
    zip(m.stranded.rows, ["station", "unit_no", "state", "unit_capacity_mw", "outage_start", "cause_group", "reason"]),
    [{ key: "station", label: "Station" }, { key: "unit_no", label: "Unit" }, { key: "state", label: "State" }, { key: "unit_capacity_mw", label: "MW", num: true, d: 0 },
      { key: "outage_start", label: "Out since" }, { key: "reason", label: "Reason" }], "CEA DGR Sub-report 10");
  const us = m.unavailable_by_state;
  tableCard(g, 12, "Unavailable capacity by state", "Average MW out per day and share of the state's monitored conventional capacity",
    zip(us, ["state", "avg_mw", "pct"]), [{ key: "state", label: "State" }, { key: "avg_mw", label: "Average MW out", num: true, d: 0 }, { key: "pct", label: "% of capacity", num: true }],
    "CEA DGR Sub-report 2");
}

function solarWindOutages(g) {
  const m = STATE.m;
  g.append(el("div", { class: "span-12 section-head" }, el("h2", { text: "Solar and wind" }),
    el("p", { text: "Capacity not available, grid events that took plants offline, and zero-output days." })));
  const cmp = m.unavailable_all_sources_pct || {};
  const keys = ["SOLAR", "WIND", "HYDRO", "NUCLEAR", "COAL", "LIGNITE", "GAS"].filter((k) => cmp[k] !== undefined && cmp[k] !== null);
  const lab = (k) => ({ COAL: "Coal", LIGNITE: "Lignite", GAS: "Gas, naphtha & diesel" })[k] || FUEL_LABEL[k];
  card(g, {
    span: 5, title: "Share of capacity unavailable, every source",
    sub: "Average over the year, %. Solar & wind: installed minus maximum available (Grid-India REMC). Others: capacity under outage (CEA). Different measures, so read as indicative.",
    source: "Grid-India REMC + CEA DGR",
    columns: [{ key: "src", label: "Source" }, { key: "pct", label: "Unavailable %", num: true }],
    rows: () => keys.map((k) => ({ src: lab(k), pct: cmp[k] })),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, grid: { ...o.grid, top: 8, right: 48 }, tooltip: { ...o.tooltip, trigger: "item", valueFormatter: (v) => `${fmt(v, 1)}%` },
        series: [{ type: "bar", barMaxWidth: 22, data: keys.map((k) => ({ value: cmp[k], itemStyle: { color: P.fuel[k], borderRadius: [0, 4, 4, 0] } })),
          label: { show: true, position: "right", color: css("--text-secondary"), fontSize: 11, formatter: (p) => `${fmt(p.value, 1)}%` } }] },
      { type: "value", axisLabel: { color: css("--text-muted"), formatter: "{value}%" }, splitLine: { lineStyle: { color: css("--grid") } } },
      { type: "category", data: keys.map(lab), inverse: true, splitLine: { show: false } });
    },
  });
  const ru = m.re_unavailable_daily;
  if (ru) {
    card(g, {
      span: 7, title: "Solar and wind capacity not available each day",
      sub: "All-India, % of REMC-monitored installed capacity (installed minus the day's maximum available)", source: "Grid-India REMC",
      columns: [{ key: "date", label: "Date" }, { key: "sp", label: "Solar %", num: true }, { key: "wp", label: "Wind %", num: true },
        { key: "sm", label: "Solar MW", num: true, d: 0 }, { key: "wm", label: "Wind MW", num: true, d: 0 }],
      rows: () => ru.dates.map((d, i) => ({ date: d, sp: ru.pct.SOLAR[i], wp: ru.pct.WIND[i], sm: ru.mw.SOLAR[i], wm: ru.mw.WIND[i] })),
      option: () => {
        const o = baseOption(), P = pal();
        return axes({ ...o, tooltip: { ...o.tooltip, ...axisTooltip("%", 1) },
          series: [["SOLAR", "Solar"], ["WIND", "Wind"]].map(([k, n]) => ({ name: n, type: "line", data: ru.pct[k], symbol: "none",
            lineStyle: { width: 2, color: P.fuel[k] }, itemStyle: { color: P.fuel[k] } })) },
        { type: "category", data: ru.dates, boundaryGap: false }, { type: "value", axisLabel: { color: css("--text-muted"), formatter: "{value}%" } });
      },
    });
    const bs = m.re_unavailable_by_state;
    card(g, {
      span: 6, size: "tall", title: "Solar and wind capacity not available, by state", sub: "Average MW not available per day (REMC-monitored states)",
      source: "Grid-India REMC",
      columns: [{ key: "state", label: "State" }, { key: "s", label: "Solar MW", num: true, d: 0 }, { key: "sp", label: "Solar %", num: true },
        { key: "w", label: "Wind MW", num: true, d: 0 }, { key: "wp", label: "Wind %", num: true }],
      rows: () => bs.states.map((st, i) => ({ state: st, s: bs.solar_mw[i], sp: bs.solar_pct[i], w: bs.wind_mw[i], wp: bs.wind_pct[i] })),
      option: () => {
        const o = baseOption(), P = pal();
        return axes({ ...o, tooltip: { ...o.tooltip, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => `${fmt(v)} MW` },
          series: [["wind_mw", "WIND", "Wind"], ["solar_mw", "SOLAR", "Solar"]].map(([c, k, n]) => ({ name: n, type: "bar", stack: "u", barMaxWidth: 18,
            data: bs[c], itemStyle: { color: P.fuel[k], borderColor: css("--surface-1"), borderWidth: 1 } })) },
        { type: "value", splitLine: { lineStyle: { color: css("--grid") } } }, { type: "category", data: bs.states, inverse: true, splitLine: { show: false } });
      },
    });
  }
  const em = m.re_events_monthly;
  if (em) {
    const kinds = [["wind", "Wind"], ["solar", "Solar"], ["solar_and_wind", "Solar & wind / hybrid"], ["other_re", "Other renewable"]];
    card(g, {
      span: 6, size: "tall", title: "Grid events that took renewable plants offline",
      sub: `Events per month: ${fmt(m.re_events_summary.n_re)} of ${fmt(m.re_events_summary.n_events)} grid disturbances in the year, ${fmt(m.re_events_summary.loss_mw)} MW of generation lost`,
      source: "Grid-India monthly grid disturbance reports",
      columns: [{ key: "month", label: "Month" }, ...kinds.map(([k, n]) => ({ key: k, label: n, num: true, d: 0 })), { key: "loss", label: "Generation lost (MW)", num: true, d: 0 }],
      rows: () => em.months.map((mo, i) => ({ month: mo, ...Object.fromEntries(kinds.map(([k]) => [k, em.series[k][i]])), loss: em.loss_mw[i] })),
      option: () => {
        const o = baseOption(), P = pal();
        return axes({ ...o, tooltip: { ...o.tooltip, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => `${fmt(v)} events` },
          series: kinds.map(([k, n], i) => ({ name: n, type: "bar", stack: "k", data: em.series[k], barMaxWidth: 24,
            itemStyle: { color: P.cause[i], borderColor: css("--surface-1"), borderWidth: 1 } })) },
        { type: "category", data: em.months.map(monthName) }, { type: "value", minInterval: 1 });
      },
    });
    tableCard(g, 12, "Largest grid events involving renewable plants", "Ranked by generation lost. The summary is the report's own sentence on the loss.",
      zip(m.re_events_top, ["event_id", "start", "end", "duration_h", "state", "category", "generation_loss_mw", "kind", "summary"]),
      [{ key: "start", label: "Start" }, { key: "duration_h", label: "Hours", num: true }, { key: "state", label: "State" }, { key: "category", label: "Category" },
        { key: "generation_loss_mw", label: "MW lost", num: true, d: 0 }, { key: "kind", label: "Plants" }, { key: "summary", label: "Summary" }],
      "Grid-India monthly grid disturbance reports");
  }
  const z = m.re_zero_output;
  if (z) {
    card(g, {
      span: 5, title: "Solar stations at zero output: how long it lasts", sub: `${fmt(z.n)} episodes across ${fmt(z.stations)} inter-state solar stations (derived proxy)`,
      source: "CEA daily RE report (derived)",
      columns: [{ key: "bin", label: "Episode length" }, { key: "n", label: "Episodes", num: true, d: 0 }],
      rows: () => z.hist.bins.map((b, i) => ({ bin: b, n: z.hist.counts[i] })),
      option: () => {
        const o = baseOption(), P = pal();
        return axes({ ...o, grid: { ...o.grid, top: 16 }, tooltip: { ...o.tooltip, trigger: "item", valueFormatter: (v) => `${fmt(v)} episodes` },
          series: [{ type: "bar", data: z.hist.counts, barMaxWidth: 24, itemStyle: barStyle(P.fuel.SOLAR) }] },
        { type: "category", data: z.hist.bins, axisLabel: { color: css("--text-muted"), fontSize: 11, interval: 0 } }, { type: "value", minInterval: 1 });
      },
    });
    tableCard(g, 7, "Solar stations with the most zero-output days", "Inter-state solar stations; stations reporting zero on more than 90% of days are excluded as not reporting",
      zip(z.top, ["station", "state", "cap", "episodes", "days"]),
      [{ key: "station", label: "Station" }, { key: "state", label: "State" }, { key: "cap", label: "MW", num: true, d: 0 },
        { key: "episodes", label: "Episodes", num: true, d: 0 }, { key: "days", label: "Zero days", num: true, d: 0 }], "CEA daily RE report (derived)");
  }
}

function tableCard(g, span, title, sub, rows, cols, source) {
  g.append(el("section", { class: `card span-${span}` }, el("h2", { text: title }), el("div", { class: "sub", text: sub }),
    el("div", { class: "table-wrap" }, renderTable(rows, cols)),
    el("div", { class: "card-actions" },
      el("button", { class: "btn", type: "button", text: "Download Excel", onclick: () => downloadRows(rows, cols, title, "xlsx") }),
      el("button", { class: "btn", type: "button", text: "CSV", onclick: () => downloadRows(rows, cols, title, "csv") }),
      el("span", { class: "spacer" }), el("span", { class: "src", text: source }))));
}

function pageSupply(root) {
  const m = STATE.m;
  head(root, "Supply and demand",
    "Peak demand and unmet demand as reported by states to Grid-India. Unmet demand is energy that could not be supplied because of shortage; it is not a count of household power cuts.");
  findings(root, "supply");
  const g = el("div", { class: "grid" }); root.append(g);
  const dd = m.demand_daily;
  card(g, {
    span: 12, title: "Peak demand met", sub: "All-India maximum demand met each day, MW", source: "Grid-India PSP",
    columns: [{ key: "date", label: "Date" }, { key: "max_demand_met_mw", label: "Peak demand met (MW)", num: true, d: 0 }, { key: "energy_met_mu", label: "Energy met (MU)", num: true }],
    rows: () => zip(dd, ["date", "max_demand_met_mw", "energy_met_mu"]),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, grid: { ...o.grid, top: 16 }, tooltip: { ...o.tooltip, ...axisTooltip("MW") },
        series: [{ name: "Peak demand met", type: "line", data: dd.max_demand_met_mw, symbol: "none", lineStyle: { width: 2, color: P.fuel.WIND }, areaStyle: { color: P.fuel.WIND, opacity: 0.1 }, itemStyle: { color: P.fuel.WIND } }] },
      { type: "category", data: dd.date, boundaryGap: false }, { type: "value", scale: true, axisLabel: { color: css("--text-muted"), formatter: (v) => fmt(v / 1000) + " GW" } });
    },
  });
  card(g, {
    span: 6, title: "Unmet demand each day", sub: "All-India energy shortage, MU", source: "Grid-India PSP",
    columns: [{ key: "date", label: "Date" }, { key: "energy_shortage_mu", label: "Energy shortage (MU)", num: true, d: 2 }],
    rows: () => zip(dd, ["date", "energy_shortage_mu"]),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, grid: { ...o.grid, top: 16 }, tooltip: { ...o.tooltip, ...axisTooltip("MU", 2) },
        series: [{ name: "Energy shortage", type: "bar", data: dd.energy_shortage_mu, barMaxWidth: 6, itemStyle: { color: P.fuel.GAS } }] },
      { type: "category", data: dd.date }, { type: "value" });
    },
  });
  card(g, {
    span: 6, title: "Generation capacity out (all sectors)", sub: "All-India generation outage reported by Grid-India, MW", source: "Grid-India PSP",
    columns: [{ key: "date", label: "Date" }, { key: "gen_outage_total_mw", label: "Generation outage (MW)", num: true, d: 0 }],
    rows: () => zip(dd, ["date", "gen_outage_total_mw"]),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, grid: { ...o.grid, top: 16 }, tooltip: { ...o.tooltip, ...axisTooltip("MW") },
        series: [{ name: "Generation outage", type: "line", data: dd.gen_outage_total_mw, symbol: "none", lineStyle: { width: 2, color: P.fuel.COAL }, itemStyle: { color: P.fuel.COAL } }] },
      { type: "category", data: dd.date, boundaryGap: false }, { type: "value", scale: true, axisLabel: { color: css("--text-muted"), formatter: (v) => fmt(v / 1000) + "k" } });
    },
  });
  const ss = m.state_shortage;
  const n = Math.min(15, ss.state.length);
  card(g, {
    span: 12, size: "tall", title: "Unmet demand by state", sub: "Total energy shortage over the year, MU (label: % of the state's demand)", source: "Grid-India PSP",
    columns: [{ key: "state", label: "State" }, { key: "shortage", label: "Energy shortage (MU)", num: true }, { key: "shortage_pct", label: "% of demand", num: true, d: 2 },
      { key: "energy", label: "Energy met (MU)", num: true, d: 0 }, { key: "peak", label: "Peak demand met (MW)", num: true, d: 0 }],
    rows: () => zip(ss, ["state", "shortage", "shortage_pct", "energy", "peak"]),
    option: () => {
      const o = baseOption(), P = pal();
      return axes({ ...o, grid: { ...o.grid, top: 8, right: 56 }, tooltip: { ...o.tooltip, trigger: "item", formatter: (p) => `${p.name}<br><b>${fmt(p.value, 1)} MU</b> (${fmt(ss.shortage_pct[p.dataIndex], 2)}% of demand)` },
        series: [{ type: "bar", barMaxWidth: 18, data: ss.shortage.slice(0, n), itemStyle: { color: P.fuel.GAS, borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: "right", color: css("--text-secondary"), fontSize: 11, formatter: (p) => `${fmt(ss.shortage_pct[p.dataIndex], 2)}%` } }] },
      { type: "value", splitLine: { lineStyle: { color: css("--grid") } } }, { type: "category", data: ss.state.slice(0, n), inverse: true, splitLine: { show: false } });
    },
  });
}

async function pageStations(root) {
  head(root, "Station explorer", "Look up any power station: generation against plan, capacity factor, capacity under outage and every outage event reported in the window.");
  const list = STATE.entities;
  const dl = el("datalist", { id: "station-list" }, list.map((e) => el("option", { value: `${e.name} · ${e.state} · ${e.fuel}` })));
  const input = el("input", { type: "search", list: "station-list", placeholder: "Search a station, e.g. Mundra, Bhadla, Kudankulam…", "aria-label": "Search station" });
  const fuelSel = el("select", { "aria-label": "Fuel filter" }, el("option", { value: "", text: "All fuels" }),
    [...new Set(list.map((e) => e.fuel))].sort().map((f) => el("option", { value: f, text: f })));
  root.append(el("div", { class: "controls" }, input, dl, fuelSel));
  const out = el("div", {}); root.append(out);
  const keyOf = (e) => `${e.name} · ${e.state} · ${e.fuel}`;
  fuelSel.addEventListener("change", () => {
    dl.replaceChildren(...list.filter((e) => !fuelSel.value || e.fuel === fuelSel.value).map((e) => el("option", { value: keyOf(e) })));
  });
  async function show(e) {
    STATE.charts = STATE.charts.filter((c) => document.body.contains(c.div));
    const d = await fetch(`data/entities/${encodeURIComponent(e.id)}.json`).then((r) => r.json());
    out.replaceChildren();
    const info = el("dl", { class: "kv" },
      ...[["Type", d.type.replace(/_/g, " ")], ["State", d.state], ["Region", d.region], ["Fuel", d.fuel], ["Sector", d.sector || "–"],
        ["Owner", d.owner || "–"], ["Latest capacity", d.capacity_mw ? `${fmt(d.capacity_mw, 1)} MW` : "–"], ["Days reported", fmt(d.days)]]
        .flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
    out.append(el("section", { class: "card", style: "margin-bottom:16px" }, el("h2", { text: d.name }), el("div", { class: "sub", text: d.id }), info));
    const g = el("div", { class: "grid" }); out.append(g);
    const s = d.series;
    const rows = () => s.date.map((dt, i) => ({ date: dt, actual_mu: s.actual_mu[i], program_mu: s.program_mu[i], capacity_mw: s.capacity_mw[i],
      capacity_factor: s.capacity_factor[i], cap_under_outage_mw: s.cap_under_outage_mw[i], coal_stock_days: s.coal_stock_days[i], source_file_id: s.source_file_id[i] }));
    const cols = [{ key: "date", label: "Date" }, { key: "actual_mu", label: "Actual (MU)", num: true, d: 3 }, { key: "program_mu", label: "Programme (MU)", num: true, d: 3 },
      { key: "capacity_mw", label: "Capacity (MW)", num: true, d: 1 }, { key: "capacity_factor", label: "Capacity factor", num: true, d: 3 },
      { key: "cap_under_outage_mw", label: "Capacity out (MW)", num: true, d: 1 }, { key: "coal_stock_days", label: "Coal stock (days)", num: true, d: 0 },
      { key: "source_file_id", label: "Source file" }];
    const P = pal(), color = P.fuel[d.fuel === "LIGNITE" ? "COAL" : d.fuel === "HYBRID" ? "SOLAR" : d.fuel] || P.fuel.WIND;
    card(g, { span: 12, title: "Daily generation", sub: s.program_mu.some((v) => v !== null) ? "Actual vs CEA programme, MU" : "Actual generation, MU", source: d.type === "conventional_station" ? "CEA DGR Sub-report 2" : "CEA daily RE report",
      columns: cols, rows,
      option: () => {
        const o = baseOption();
        const series = [{ name: "Actual", type: "line", data: s.actual_mu, symbol: "none", lineStyle: { width: 2, color }, itemStyle: { color }, areaStyle: { color, opacity: 0.1 } }];
        if (s.program_mu.some((v) => v !== null)) series.push({ name: "Programme", type: "line", data: s.program_mu, symbol: "none", lineStyle: { width: 2, color: css("--text-muted"), type: "dashed" }, itemStyle: { color: css("--text-muted") } });
        return axes({ ...o, tooltip: { ...o.tooltip, ...axisTooltip("MU", 2) }, series }, { type: "category", data: s.date, boundaryGap: false }, { type: "value" });
      } });
    if (s.cap_under_outage_mw.some((v) => v)) {
      card(g, { span: 12, size: "short", title: "Capacity under outage", sub: "MW reported out each day", source: "CEA DGR Sub-report 2", columns: cols, rows,
        option: () => { const o = baseOption(); return axes({ ...o, grid: { ...o.grid, top: 16 }, tooltip: { ...o.tooltip, ...axisTooltip("MW", 1) },
          series: [{ name: "Capacity out", type: "line", step: "middle", data: s.cap_under_outage_mw, symbol: "none", lineStyle: { width: 2, color: pal().cause[1] }, itemStyle: { color: pal().cause[1] }, areaStyle: { color: pal().cause[1], opacity: 0.1 } }] },
          { type: "category", data: s.date, boundaryGap: false }, { type: "value" }); } });
    }
    if (d.zero_episodes && d.zero_episodes.length) {
      tableCard(g, 12, "Zero-output episodes (" + d.zero_episodes.length + ")", "Consecutive days on which this solar station reported zero generation (derived from CEA's daily RE report)",
        d.zero_episodes, [{ key: "first", label: "From" }, { key: "last", label: "To" }, { key: "days", label: "Days", num: true, d: 0 }], "CEA daily RE report (derived)");
    }
    if (d.events.length) {
      tableCard(g, 12, `Outage events (${d.events.length})`, "Reconstructed from CEA's daily outage reports (coal, lignite and nuclear units)", d.events.map((e) => ({ ...e, cause: CAUSE_LABEL[e.cause] || e.cause })),
        [{ key: "unit", label: "Unit" }, { key: "start", label: "Start" }, { key: "end", label: "Reported return" }, { key: "end_status", label: "End" },
          { key: "duration_h", label: "Hours", num: true }, { key: "mw", label: "MW", num: true, d: 0 }, { key: "cause", label: "Cause" }, { key: "reason", label: "Reason" }], "CEA DGR Sub-report 10");
    }
  }
  input.addEventListener("change", () => { const e = list.find((x) => keyOf(x) === input.value); if (e) show(e); });
  const first = list.find((e) => /MUNDRA TPP - I/.test(e.name)) || list[0];
  input.value = keyOf(first); show(first);
}

function pageData(root) {
  const m = STATE.m, cat = STATE.catalog;
  head(root, "Data & downloads", `Every table in this release, ${m.window[0]} to ${m.window[1]}. The core table holds one record per station (or state-level renewable total) per day across every energy source.`);
  const g = el("div", { class: "grid" }); root.append(g);
  const sizes = (b) => (b > 1e6 ? `${fmt(b / 1e6, 1)} MB` : `${fmt(b / 1e3, 0)} KB`);
  const t = el("table");
  t.append(el("thead", {}, el("tr", {}, ["Table", "Rows", "What it contains", "Download"].map((h) => el("th", { text: h, class: h === "Rows" ? "num" : "" })))));
  const tb = el("tbody");
  for (const c of cat) {
    const links = el("td", {}, ...Object.entries(c.files).flatMap(([k, f]) => [el("a", { href: `data/downloads/${f.path}`, download: "", text: `${k === "csv" ? "CSV (zip)" : k === "xlsx" ? "Excel" : "Parquet"} · ${sizes(f.bytes)}` }), " "]));
    const desc = el("td", { style: "white-space:normal;min-width:280px" }, c.description, " ",
      el("details", {}, el("summary", { text: `${c.columns.length} columns` }),
        el("ul", {}, c.columns.map((col) => el("li", {}, el("code", { text: col.name }), " ", col.description)))));
    tb.append(el("tr", {}, el("td", {}, el("code", { text: c.table })), el("td", { class: "num", text: fmt(c.rows) }), desc, links));
  }
  t.append(tb);
  g.append(el("section", { class: "card span-12" }, el("h2", { text: "Dataset" }),
    el("div", { class: "sub", text: "Excel files include an 'about' sheet describing every column. The release manifest lists the official URL and SHA-256 of every source file used." }),
    el("div", { class: "table-wrap", style: "max-height:none" }, t),
    el("div", { class: "card-actions" }, el("a", { class: "btn", href: "data/release_manifest.json", download: "", text: "Release manifest (JSON)" }))));
  const cov = m.coverage.files;
  const covRows = Object.entries(cov).map(([k, v]) => ({ source: k, ok: v.ok, total: v.total, missing: v.missing.join(", ") || "none" }));
  tableCard(g, 6, "Coverage", "Days with a successfully downloaded report, per source. Missing days stay missing; nothing is estimated.",
    covRows, [{ key: "source", label: "Source / report" }, { key: "ok", label: "Days", num: true, d: 0 }, { key: "total", label: "Of", num: true, d: 0 }, { key: "missing", label: "Missing dates" }], "manifest");
  const vt = el("table");
  vt.append(el("thead", {}, el("tr", {}, ["Check", "Result", "Detail"].map((h) => el("th", { text: h })))));
  const vb = el("tbody");
  for (const v of m.validation) vb.append(el("tr", {}, el("td", { text: v.check }), el("td", { class: `status-${v.status}`, text: v.status.toUpperCase() }), el("td", { text: v.detail, style: "white-space:normal" })));
  vt.append(vb);
  g.append(el("section", { class: "card span-6" }, el("h2", { text: "Validation checks" }), el("div", { class: "sub", text: "Cross-checks run on every build" }), el("div", { class: "table-wrap" }, vt)));
  g.append(el("section", { class: "card span-12 prose" }, el("h2", { text: "Rebuild the dataset yourself" }),
    el("p", { text: "The whole dataset is rebuilt from the official websites with one command. It downloads every report for the window in observatory.yaml, parses, validates, merges and writes these files:" }),
    el("pre", {}, el("code", { text: "python -m observatory refresh --fresh" })),
    el("p", { text: "--fresh ignores anything downloaded before, so every file comes straight from npp.gov.in, gen-re.cea.gov.in and grid-india.in." })));
}

function pageMethod(root) {
  head(root, "Methodology", "Where the numbers come from, what they mean, and what they do not measure.");
  const p = el("div", { class: "prose" });
  const sec = (h, items) => { p.append(el("h2", { text: h }), el("ul", {}, items.map((t) => el("li", { text: t })))); };
  sec("Sources", [
    "CEA Daily Generation Report (npp.gov.in): Sub-report 2 for station- and unit-level generation, programme, capacity and outage status of conventional plants (coal, lignite, gas, naphtha, diesel, nuclear, large hydro); Sub-report 10 for the daily list of coal, lignite and nuclear units under outage with reasons; Sub-report 17 for CEA's own fuel totals.",
    "CEA Daily Renewable Generation Report (gen-re.cea.gov.in): wind, solar and other renewable generation by state (state-embedded plants) and by inter-state-connected (ISGS) station.",
    "Grid-India daily Power Supply Position report (grid-india.in): source-wise gross generation by region including renewables, state demand and energy shortage, generation outage, and 15-minute SCADA generation by source.",
    "Grid-India daily REMC (Renewable Energy Management Centre) report: solar and wind installed vs maximum available capacity by region and state, and curtailment.",
    "Grid-India monthly grid disturbance reports: every grid disturbance and incident with start, end, generation lost and a narrative naming the affected plants.",
  ]);
  sec("Definitions", [
    "Renewable = solar, wind, large hydro, biomass and other renewables. Nuclear is shown separately: non-renewable but low-carbon. Fossil = coal, lignite, gas, naphtha, diesel.",
    "Generation shares use Grid-India's gross figures, which cover every source on one basis. CEA's renewable report is net generation and is never added to gross figures in a single total.",
    "Capacity factor = actual generation ÷ (capacity × 24 h). Solar and wind capacity factors use inter-state stations, whose capacity is reported daily.",
    "Variability = coefficient of variation (standard deviation ÷ mean) of daily output. Variable output is the nature of the resource, not a reliability failure.",
    "Capacity unavailable = capacity CEA reports under outage ÷ monitored capacity. For gas plants this includes plants idle for lack of gas or schedule.",
    "Outage cause groups come from CEA's planned/forced columns and the reported reason text (reference/outage_reasons.csv): planned maintenance, equipment failure, fuel supply, commercial (no schedule / reserve shutdown), long-term or retiring, regulatory and other.",
    "Outage events link daily snapshots by unit and outage start time. Durations are given only when a return time was reported.",
  ]);
  sec("What this does not measure", [
    "No official source lists outages of individual solar or wind units. Three official proxies are used instead: REMC unavailable capacity (aggregate, by region and state), Grid-India grid-disturbance events that took renewable plants offline (event level, mostly evacuation-line trips), and zero-output days of inter-state solar stations (derived from CEA).",
    "A generating-unit outage is not a consumer power cut. Unmet demand (energy shortage) is reported by states and is not a household interruption measure such as SAIFI or SAIDI.",
    "Rooftop and behind-the-meter solar is not in grid generation data.",
    "This release covers one year, so seasonal patterns are shown but multi-year trends are not.",
  ]);
  sec("Data handling", [
    "Values are kept exactly as published. Implausible values are flagged (quality_flag), never edited.",
    "Missing reports stay missing and are listed under Coverage; nothing is interpolated.",
    "Only two merges change the published structure: Daman & Diu and Dadra & Nagar Haveli are summed (one UT since 2020), and rows that a report repeats when a long remark wraps are merged into one.",
  ]);
  root.append(p);
}

/* ------------------------------------------------------------------ router */
const PAGES = { overview: pageOverview, mix: pageMix, renewables: pageRenewables, outages: pageOutages, supply: pageSupply,
  stations: pageStations, data: pageData, method: pageMethod };
function route() {
  const page = (location.hash || "#overview").slice(1);
  const fn = PAGES[page] || pageOverview;
  STATE.charts.forEach((c) => c.chart && c.chart.dispose());
  STATE.charts = [];
  const root = document.getElementById("app");
  root.replaceChildren();
  document.querySelectorAll(".tabs a").forEach((a) => a.toggleAttribute("aria-current", a.getAttribute("href") === "#" + (PAGES[page] ? page : "overview")));
  document.querySelectorAll(".tabs a[aria-current]").forEach((a) => a.setAttribute("aria-current", "page"));
  fn(root);
  window.scrollTo(0, 0);
}
function redrawAll() { STATE.charts.forEach((c) => document.body.contains(c.div) && c.draw()); }

const THEMES = ["auto", "light", "dark"];
function applyTheme(t) {
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  document.getElementById("theme-btn").textContent = `Theme: ${t}`;
  try { localStorage.setItem("theme", t); } catch (e) { /* storage unavailable */ }
  redrawAll();
}

async function boot() {
  let saved = "auto";
  try { saved = localStorage.getItem("theme") || "auto"; } catch (e) { /* storage unavailable */ }
  applyTheme(saved);
  document.getElementById("theme-btn").addEventListener("click", () => {
    const cur = document.getElementById("theme-btn").textContent.replace("Theme: ", "");
    applyTheme(THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length]);
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redrawAll);
  const get = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(p); return r.json(); });
  try {
    [STATE.m, STATE.ins, STATE.entities, STATE.catalog] = await Promise.all(
      [get("data/metrics.json"), get("data/insights.json"), get("data/entities.json"), get("data/catalog.json")]);
  } catch (e) {
    document.getElementById("app").replaceChildren(el("p", { class: "loading", text: "Could not load data. Run `python -m observatory refresh`, then serve this folder over HTTP (python -m http.server -d dashboard)." }));
    return;
  }
  document.getElementById("window-label").textContent = `Official CEA & Grid-India data · ${dateName(STATE.m.window[0])} – ${dateName(STATE.m.window[1])}`;
  window.addEventListener("hashchange", route);
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => STATE.charts.forEach((c) => c.chart && c.chart.resize()), 150); });
  route();
}
document.addEventListener("DOMContentLoaded", boot);
