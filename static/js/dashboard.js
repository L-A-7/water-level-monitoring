// bufferDays: how much data to actually fetch for a given preset, beyond
// what's initially shown — so zooming/panning out from e.g. 24h to a few
// days doesn't need a fresh request. null means "fetch just this preset's
// own window" (already the widest tier, or intentionally unbounded).
// gridMinutes: the fixed time-grid step charted points get snapped onto (see
// griddedSeries() below) -- lightweight-charts spaces points evenly by
// index, not by their actual timestamp gap (github.com/tradingview/
// lightweight-charts issues #457, #1426), so without this, irregular
// sampling (a burst of 1min-apart backlog readings vs. a normal 15min gap)
// renders as if evenly spaced in time, badly distorting the shape of the
// curve. Finer for tighter ranges (needs to resolve short gaps without
// collapsing readings together), coarser for wide ranges (keeps the point
// count sane over weeks/months).
const RANGE_PRESETS = [
  { key: "24h", label: "24h", days: 1, bufferDays: 7, gridMinutes: 1 },
  { key: "7", label: "7d", days: 7, bufferDays: 30, gridMinutes: 15 },
  { key: "30", label: "30d", days: 30, bufferDays: 60, gridMinutes: 60 },
  { key: "60", label: "60d", days: 60, bufferDays: null, gridMinutes: 60 },
  { key: "all", label: "All", days: null, bufferDays: null, gridMinutes: 60 },
];
const DEFAULT_RANGE = "60";

const TANK_ENHANCED_DAYS = 60;

// Approximate pixel height of the divider lightweight-charts draws between
// stacked panes — used to convert a lower pane's own-coordinate y position
// (from priceToCoordinate) into a position relative to the whole container.
const PANE_SEPARATOR = 6;

const MOBILE_QUERY = window.matchMedia("(max-width: 640px)");
const DARK_QUERY = window.matchMedia("(prefers-color-scheme: dark)");

// Each group is one lightweight-charts instance with two stacked panes
// sharing a time axis (and therefore zoom/pan + crosshair), but each pane
// keeps its own independent price scale — no dual-axis overlap. Zooming is
// independent between the two groups, since they're separate chart instances.
const GROUP_DEFS = {
  levelTemp: {
    containerId: "level-temp-chart",
    cardId: "level-temp-chart-card",
    emptyId: "level-temp-empty-state",
    rangeCookie: "tank_range_level_temp",
    tableWrapId: "level-temp-table-wrap",
    tableBodyId: "level-temp-table-body",
    csvHeaders: ["Time", "Level (cm)", "Temp (°C)", "Battery (V)", "RSSI (dBm)"],
    tableColumns: [
      (r) => fmtTime(r.time),
      (r) => (r.level_cm !== null ? fmtNumber(r.level_cm, 1) : "no echo"),
      (r) => (r.chip_temp_c !== null ? fmtNumber(r.chip_temp_c, 1) : "—"),
      (r) => (r.battery_mv !== null && r.battery_mv !== undefined ? fmtNumber(r.battery_mv / 1000, 2) : "—"),
      (r) => (r.rssi !== null ? fmtNumber(r.rssi) : "—"),
    ],
    paneHeights: [405, 135],
    paneHeightsMobile: [315, 105],
    series: [
      {
        key: "level",
        type: "area",
        color: () => cssVar("--series-1"),
        areaTopColor: () => cssVar("--series-1-area-top"),
        areaBottomColor: () => cssVar("--series-1-area-bottom"),
        priceFormat: { type: "price", precision: 1, minMove: 0.1 },
        decimals: 1,
        unit: "cm",
        label: "Level",
        extract: (r) => r.level_cm,
      },
      {
        key: "temp",
        type: "area",
        color: () => cssVar("--series-2"),
        areaTopColor: () => cssVar("--series-2-area-top"),
        areaBottomColor: () => cssVar("--series-2-area-bottom"),
        priceFormat: { type: "price", precision: 1, minMove: 0.1 },
        decimals: 1,
        unit: "°C",
        label: "Temp",
        extract: (r) => r.chip_temp_c,
      },
    ],
  },
  voltageRssi: {
    containerId: "voltage-rssi-chart",
    cardId: "voltage-rssi-chart-card",
    emptyId: "voltage-rssi-empty-state",
    rangeCookie: "tank_range_voltage_rssi",
    paneHeights: [240, 120],
    paneHeightsMobile: [187, 93],
    series: [
      {
        key: "voltage",
        type: "area",
        color: () => cssVar("--series-3"),
        areaTopColor: () => cssVar("--series-3-area-top"),
        areaBottomColor: () => cssVar("--series-3-area-bottom"),
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        decimals: 2,
        unit: "V",
        label: "Battery",
        extract: (r) => (r.battery_mv !== null && r.battery_mv !== undefined ? r.battery_mv / 1000 : null),
      },
      {
        key: "rssi",
        type: "area",
        color: () => cssVar("--series-4"),
        areaTopColor: () => cssVar("--series-4-area-top"),
        areaBottomColor: () => cssVar("--series-4-area-bottom"),
        priceFormat: { type: "price", precision: 0, minMove: 1 },
        decimals: 0,
        unit: "dBm",
        label: "RSSI",
        extract: (r) => r.rssi,
      },
    ],
  },
  // Admin-only: its container only exists in _dashboard.html when {% if
  // admin %} is true, so availableGroupKeys() filters this out on the
  // public page automatically.
  distanceStd: {
    containerId: "distance-std-chart",
    cardId: "distance-std-chart-card",
    emptyId: "distance-std-empty-state",
    rangeCookie: "tank_range_distance_std",
    tableWrapId: "distance-std-table-wrap",
    tableBodyId: "distance-std-table-body",
    csvHeaders: ["Time", "Distance std dev (cm)"],
    tableColumns: [
      (r) => fmtTime(r.time),
      (r) => (r.distance_std_cm !== null && r.distance_std_cm !== undefined ? fmtNumber(r.distance_std_cm, 2) : "—"),
    ],
    paneHeights: [220],
    paneHeightsMobile: [170],
    series: [
      {
        key: "distanceStd",
        type: "area",
        color: () => cssVar("--series-5"),
        areaTopColor: () => cssVar("--series-5-area-top"),
        areaBottomColor: () => cssVar("--series-5-area-bottom"),
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        decimals: 2,
        unit: "cm",
        label: "Std dev",
        extract: (r) => r.distance_std_cm,
      },
    ],
  },
};

function availableGroupKeys() {
  return Object.keys(GROUP_DEFS).filter((key) => document.getElementById(GROUP_DEFS[key].containerId));
}

const state = {
  groups: {},
  tableVisible: {},
  readings: {},
};

function getCookie(name) {
  const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return match ? decodeURIComponent(match[1]) : null;
}

function setCookie(name, value) {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=31536000; samesite=lax`;
}

function rangeStartIso(days) {
  if (days === null) return null;
  const d = new Date();
  d.setTime(d.getTime() - days * 24 * 60 * 60 * 1000);
  return d.toISOString();
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function fmtNumber(n, decimals = 0) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: decimals, minimumFractionDigits: decimals });
}

function fmtTime(iso) {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDateOnly(isoDate) {
  return new Date(isoDate).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function unixSeconds(iso) {
  return Math.floor(new Date(iso).getTime() / 1000);
}

function pointsFor(readings, extract) {
  const points = [];
  for (const r of readings) {
    const v = extract(r);
    if (v === null || v === undefined) continue;
    points.push({ time: unixSeconds(r.time), value: v });
  }
  return points;
}

// Snaps points onto a fixed-step time grid and fills every empty tick in
// between with a whitespace point (time only, no value) -- so consecutive
// chart indices are always exactly gridMinutes apart in real time, and
// gaps/bursts in the underlying sampling render proportionally instead of
// getting stretched or squeezed to a uniform per-point width. Ticks that
// land more than one raw point (a tighter burst than the chosen grid) keep
// the most recent reading in that slot.
function griddedSeries(points, gridMinutes) {
  const stepSec = gridMinutes * 60;
  const snapped = new Map();
  for (const p of points) {
    snapped.set(Math.round(p.time / stepSec) * stepSec, p.value);
  }
  if (snapped.size === 0) return [];

  const ticks = [...snapped.keys()].sort((a, b) => a - b);
  const result = [];
  for (let t = ticks[0]; t <= ticks[ticks.length - 1]; t += stepSec) {
    result.push(snapped.has(t) ? { time: t, value: snapped.get(t) } : { time: t });
  }
  return result;
}

// lightweight-charts formats its native time axis (tick labels + crosshair
// date label) using UTC by default, regardless of viewer timezone -- while
// every other timestamp in this dashboard (fmtTime, stat panels) uses
// toLocaleString(), i.e. the browser's local time. Without these overrides
// the chart axis reads a fixed UTC-offset number of hours off from
// everything else on the page.
function localCrosshairTimeFormatter(time) {
  return new Date(time * 1000).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function localTickMarkFormatter(time, tickMarkType, locale) {
  const d = new Date(time * 1000);
  const TickMarkType = LightweightCharts.TickMarkType;
  switch (tickMarkType) {
    case TickMarkType.Year:
      return d.toLocaleDateString(locale, { year: "numeric" });
    case TickMarkType.Month:
      return d.toLocaleDateString(locale, { month: "short", year: "numeric" });
    case TickMarkType.DayOfMonth:
      return d.toLocaleDateString(locale, { day: "numeric", month: "short" });
    case TickMarkType.Time:
      return d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
    case TickMarkType.TimeWithSeconds:
      return d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    default:
      return d.toLocaleString(locale);
  }
}

function baseChartOptions() {
  const gridline = cssVar("--gridline");
  const axis = cssVar("--axis");
  const surface = cssVar("--surface");
  const muted = cssVar("--text-muted");
  // Same subtle divider used for .stat-sep between the two stat blocks in
  // each header — a bit more present than the plot gridlines, without
  // visually splitting the pair apart.
  const paneSeparator = cssVar("--border");

  return {
    autoSize: true,
    layout: {
      background: { type: "solid", color: surface },
      textColor: muted,
      fontSize: 12,
      attributionLogo: false,
      panes: {
        separatorColor: paneSeparator,
        separatorHoverColor: paneSeparator,
        enableResize: false,
      },
    },
    grid: {
      vertLines: { color: gridline },
      horzLines: { color: gridline },
    },
    rightPriceScale: {
      borderColor: axis,
      visible: true,
    },
    leftPriceScale: {
      visible: false,
    },
    localization: {
      timeFormatter: localCrosshairTimeFormatter,
    },
    timeScale: {
      borderColor: axis,
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: localTickMarkFormatter,
      // lightweight-charts' fitContent() won't compress bars below the
      // *current* barSpacing, only ever widening it — so the initial value
      // has to already be small, or dense ranges (60d/All) get truncated
      // to whatever fits at the default 6px/bar instead of showing it all.
      barSpacing: 0.1,
      minBarSpacing: 0.01,
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      // The date shows once, natively, on the shared time axis at the
      // bottom — our own per-pane tooltips only need to carry the value.
      vertLine: { color: axis, width: 1, style: LightweightCharts.LineStyle.Solid, labelVisible: true },
      horzLine: { color: axis, width: 1, style: LightweightCharts.LineStyle.Solid },
    },
    // Time (horizontal) zoom/pan only. Vertical touch-drag is disabled so a
    // vertical swipe over the chart falls through to normal page scrolling
    // instead of panning the price scale. Price-axis drag-to-zoom is
    // disabled too -- it let a stray touch lock the price scale into a
    // manual range with no obvious way back (autoScale stays in control of
    // the vertical scale, so it always fits the visible data).
    handleScroll: {
      mouseWheel: true,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: false,
    },
    handleScale: {
      mouseWheel: true,
      pinch: true,
      axisPressedMouseMove: { time: true, price: false },
      axisDoubleClickReset: { time: true, price: true },
    },
  };
}

function createGroupChart(def) {
  const container = document.getElementById(def.containerId);
  const chart = LightweightCharts.createChart(container, baseChartOptions());

  const seriesEntries = {};
  def.series.forEach((sdef, paneIndex) => {
    const color = sdef.color();
    const seriesBase = {
      priceFormat: sdef.priceFormat,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerRadius: 4,
    };

    const series =
      sdef.type === "area"
        ? chart.addSeries(
            LightweightCharts.AreaSeries,
            {
              ...seriesBase,
              lineColor: color,
              topColor: sdef.areaTopColor(),
              bottomColor: sdef.areaBottomColor(),
              lineWidth: 2,
            },
            paneIndex,
          )
        : chart.addSeries(LightweightCharts.LineSeries, { ...seriesBase, color, lineWidth: 2 }, paneIndex);

    const tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    container.parentElement.appendChild(tooltip);

    seriesEntries[sdef.key] = { series, tooltip, paneIndex, def: sdef, points: [], pointsMap: new Map() };
  });

  chart.subscribeCrosshairMove((param) => {
    updateGroupTooltips(def, container, chart, seriesEntries, param);
  });

  return { chart, container, seriesEntries };
}

function paneYOffset(def, paneIndex) {
  const heights = MOBILE_QUERY.matches ? def.paneHeightsMobile : def.paneHeights;
  let offset = 0;
  for (let i = 0; i < paneIndex; i++) offset += heights[i] + PANE_SEPARATOR;
  return offset;
}

function applyPaneHeights() {
  const mobile = MOBILE_QUERY.matches;
  for (const key of availableGroupKeys()) {
    const def = GROUP_DEFS[key];
    const group = state.groups[key];
    const heights = mobile ? def.paneHeightsMobile : def.paneHeights;
    heights.forEach((height, i) => group.chart.panes()[i].setHeight(height));
  }
}

// Chart colors are baked into the canvas at creation/update time (they're
// not live CSS like the rest of the page), so a light<->dark switch that
// happens without a full reload -- the OS flipping theme while the tab
// stays open -- would otherwise leave the charts stuck on their original
// colors. Re-read the CSS vars and push them back into the chart whenever
// the media query flips.
function applyTheme() {
  for (const key of availableGroupKeys()) {
    const def = GROUP_DEFS[key];
    const group = state.groups[key];
    group.chart.applyOptions(baseChartOptions());
    for (const sdef of def.series) {
      const entry = group.seriesEntries[sdef.key];
      entry.series.applyOptions(
        sdef.type === "area"
          ? { lineColor: sdef.color(), topColor: sdef.areaTopColor(), bottomColor: sdef.areaBottomColor() }
          : { color: sdef.color() },
      );
    }
  }
}

function initGroupCharts() {
  for (const key of availableGroupKeys()) {
    state.groups[key] = createGroupChart(GROUP_DEFS[key]);
  }
  applyPaneHeights();
  MOBILE_QUERY.addEventListener("change", applyPaneHeights);
  DARK_QUERY.addEventListener("change", applyTheme);
}

function updateGroupTooltips(def, container, chart, seriesEntries, param) {
  const x = param.time ? chart.timeScale().timeToCoordinate(param.time) : null;

  for (const entry of Object.values(seriesEntries)) {
    const value = param.time !== undefined ? entry.pointsMap.get(param.time) : undefined;
    const yInPane = value !== undefined ? entry.series.priceToCoordinate(value) : null;
    if (value === undefined || x === null || yInPane === null) {
      entry.tooltip.style.display = "none";
      continue;
    }
    const y = yInPane + paneYOffset(def, entry.paneIndex);

    entry.tooltip.innerHTML = `<strong>${fmtNumber(value, entry.def.decimals)} ${entry.def.unit}</strong>`;
    entry.tooltip.style.display = "block";
    const maxLeft = Math.max(container.clientWidth - entry.tooltip.offsetWidth - 4, 4);
    entry.tooltip.style.left = `${Math.min(Math.max(x + 12, 4), maxLeft)}px`;
    entry.tooltip.style.top = `${Math.max(y - 32, 4)}px`;
  }
}

function updateGroupChart(key, readings, visibleRange, gridMinutes) {
  const def = GROUP_DEFS[key];
  const group = state.groups[key];
  let anyPoints = false;

  for (const sdef of def.series) {
    const entry = group.seriesEntries[sdef.key];
    const points = griddedSeries(pointsFor(readings, sdef.extract), gridMinutes);
    entry.points = points;
    entry.pointsMap = new Map(points.filter((p) => p.value !== undefined).map((p) => [p.time, p.value]));
    entry.series.setData(points);
    if (points.length) anyPoints = true;
  }

  if (visibleRange) {
    group.chart.timeScale().setVisibleRange(visibleRange);
  } else {
    group.chart.timeScale().fitContent();
  }
  document.getElementById(def.emptyId).style.display = anyPoints ? "none" : "flex";
}

function renderSummary(data) {
  document.getElementById("stat-last-reading-time").textContent = data.last_reading_time ? fmtTime(data.last_reading_time) : "—";
  const hasSamplePeriod = data.wakeup_period_min !== null && data.wakeup_period_min !== undefined;
  document.getElementById("stat-sample-period-wrap").style.display = hasSamplePeriod ? "" : "none";
  if (hasSamplePeriod) {
    document.getElementById("stat-sample-period").textContent = data.wakeup_period_min;
  }

  document.getElementById("stat-level").textContent = data.level_cm !== null ? fmtNumber(data.level_cm, 1) : "—";
  document.getElementById("stat-distance").textContent =
    data.distance_cm !== null && data.distance_cm !== undefined
      ? `Sensor to water ≈ ${fmtNumber(data.distance_cm, 1)} cm`
      : "Sensor to water = —";

  const emptyDateEl = document.getElementById("stat-empty-date");
  if (data.tank_empty_date) {
    emptyDateEl.textContent = `Estimated empty date: ${fmtDateOnly(data.tank_empty_date)}`;
    emptyDateEl.classList.toggle("enhanced", data.tank_empty_days !== null && data.tank_empty_days <= TANK_ENHANCED_DAYS);
  } else {
    emptyDateEl.textContent = "Estimated empty date: —";
    emptyDateEl.classList.remove("enhanced");
  }

  document.getElementById("stat-temp").textContent = data.chip_temp_c !== null ? fmtNumber(data.chip_temp_c, 1) : "—";

  document.getElementById("stat-battery").textContent = data.battery_v !== null ? fmtNumber(data.battery_v, 2) : "—";
  document.getElementById("stat-battery-recharge").textContent = data.battery_critical_date
    ? `Est. recharge by: ${fmtDateOnly(data.battery_critical_date)}`
    : "Est. recharge: —";
  const rssiEl = document.getElementById("stat-rssi");
  rssiEl.textContent = data.rssi !== null && data.rssi !== undefined ? fmtNumber(data.rssi) : "—";
  rssiEl.classList.toggle("status-warning", Boolean(data.weak_signal_warning));
}

function renderGroupTable(key, readings) {
  const def = GROUP_DEFS[key];
  const tbody = document.getElementById(def.tableBodyId);
  tbody.innerHTML = "";
  for (const r of [...readings].reverse()) {
    const tr = document.createElement("tr");
    for (const cellValue of def.tableColumns) {
      const td = document.createElement("td");
      td.textContent = cellValue(r);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

async function loadGroupRange(key, presetKey) {
  const def = GROUP_DEFS[key];
  const preset = RANGE_PRESETS.find((p) => p.key === presetKey) || RANGE_PRESETS.find((p) => p.key === DEFAULT_RANGE);

  document.querySelectorAll(`.range-pills[data-group="${key}"] button[data-range]`).forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.range === preset.key);
  });
  setCookie(def.rangeCookie, preset.key);

  const fetchDays = preset.bufferDays !== null ? preset.bufferDays : preset.days;
  const params = new URLSearchParams();
  const start = rangeStartIso(fetchDays);
  if (start) params.set("start", start);

  const res = await fetch(`/watertank/api/readings?${params.toString()}`);
  const data = await res.json();

  let visibleRange = null;
  if (preset.days !== null && data.readings.length) {
    const to = unixSeconds(data.readings[data.readings.length - 1].time);
    const from = to - preset.days * 24 * 60 * 60;
    visibleRange = { from, to };
  }

  updateGroupChart(key, data.readings, visibleRange, preset.gridMinutes);
  state.readings[key] = data.readings;
  if (def.tableWrapId) renderGroupTable(key, data.readings);
}

// Same "—" / "no echo" placeholders as the on-page table (tableColumns),
// just quoted properly for a CSV cell instead of rendered as text.
function toCsv(headers, rows) {
  const escapeCell = (value) => {
    const s = String(value);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [headers, ...rows].map((row) => row.map(escapeCell).join(",")).join("\r\n");
}

function downloadGroupCsv(key) {
  const def = GROUP_DEFS[key];
  const readings = state.readings[key] || [];
  const rows = readings.map((r) => def.tableColumns.map((col) => col(r)));
  const csv = toCsv(def.csvHeaders, rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${key}-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

async function loadSummary() {
  const res = await fetch("/watertank/api/summary");
  const data = await res.json();
  renderSummary(data);
}

function initRangePills() {
  for (const key of availableGroupKeys()) {
    document.querySelectorAll(`.range-pills[data-group="${key}"] button[data-range]`).forEach((btn) => {
      btn.addEventListener("click", () => loadGroupRange(key, btn.dataset.range));
    });
  }
}

function initTableToggles() {
  for (const key of availableGroupKeys()) {
    const def = GROUP_DEFS[key];
    if (!def.tableWrapId) continue;
    const toggle = document.querySelector(`.table-toggle[data-toggle="${key}"]`);
    const tableWrap = document.getElementById(def.tableWrapId);
    const chartCard = document.getElementById(def.cardId);
    state.tableVisible[key] = false;
    toggle.addEventListener("click", () => {
      state.tableVisible[key] = !state.tableVisible[key];
      tableWrap.style.display = state.tableVisible[key] ? "block" : "none";
      chartCard.style.display = state.tableVisible[key] ? "none" : "block";
      toggle.textContent = state.tableVisible[key] ? "View as chart" : "View as table";
    });
  }
}

function initCsvDownloads() {
  for (const key of availableGroupKeys()) {
    const def = GROUP_DEFS[key];
    if (!def.csvHeaders) continue;
    const button = document.querySelector(`[data-csv="${key}"]`);
    button.addEventListener("click", () => downloadGroupCsv(key));
  }
}

// Admin-only (see _dashboard.html's {% if admin %} block): raw HC-SR04
// per-ping samples behind a filtered reading, per device.md's temporary
// samples_cm diagnostic field. Only readings captured while
// DEBUG_SEND_RAW_SAMPLES is flashed on the device carry these.
async function loadRawSamplesList() {
  const select = document.getElementById("raw-samples-select");
  if (!select) return;

  const res = await fetch("/watertank/api/admin/raw-samples");
  const readings = await res.json();

  const emptyState = document.getElementById("raw-samples-empty-state");
  const controls = document.querySelector(".raw-samples-controls");
  const tableWrap = document.getElementById("raw-samples-table-wrap");

  if (!readings.length) {
    emptyState.style.display = "block";
    controls.style.display = "none";
    tableWrap.style.display = "none";
    return;
  }
  emptyState.style.display = "none";
  controls.style.display = "flex";
  tableWrap.style.display = "block";

  select.innerHTML = "";
  for (const r of readings) {
    const opt = document.createElement("option");
    opt.value = r.id;
    const distanceLabel =
      r.distance_cm !== null && r.distance_cm !== undefined ? `${fmtNumber(r.distance_cm, 2)} cm` : "no echo";
    opt.textContent = `${fmtTime(r.time)} — ${distanceLabel} (${r.sample_count} samples)`;
    select.appendChild(opt);
  }

  select.addEventListener("change", () => loadRawSamplesDetail(select.value));
  await loadRawSamplesDetail(select.value);
}

async function loadRawSamplesDetail(readingId) {
  const res = await fetch(`/watertank/api/admin/raw-samples/${readingId}`);
  const data = await res.json();
  state.rawSamples = data;

  const tbody = document.getElementById("raw-samples-table-body");
  tbody.innerHTML = "";
  data.samples_cm.forEach((value, i) => {
    const tr = document.createElement("tr");
    const idxTd = document.createElement("td");
    idxTd.textContent = i + 1;
    const valTd = document.createElement("td");
    valTd.textContent = value === -1 ? "no echo" : fmtNumber(value, 2);
    tr.appendChild(idxTd);
    tr.appendChild(valTd);
    tbody.appendChild(tr);
  });
}

function downloadRawSamplesCsv() {
  const data = state.rawSamples;
  if (!data) return;
  const rows = data.samples_cm.map((value, i) => [i + 1, value === -1 ? "no echo" : value]);
  const csv = toCsv(["#", "Raw distance (cm)"], rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `raw-samples-${data.id}-${new Date(data.time).toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

document.addEventListener("DOMContentLoaded", () => {
  initGroupCharts();
  initRangePills();
  initTableToggles();
  initCsvDownloads();
  for (const key of availableGroupKeys()) {
    const savedRange = getCookie(GROUP_DEFS[key].rangeCookie) || DEFAULT_RANGE;
    loadGroupRange(key, savedRange);
  }
  loadSummary();
  loadRawSamplesList();
  document.getElementById("raw-samples-download")?.addEventListener("click", downloadRawSamplesCsv);
});
