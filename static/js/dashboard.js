const RANGE_PRESETS = [
  { key: "24h", label: "24h", days: 1 },
  { key: "7", label: "7d", days: 7 },
  { key: "30", label: "30d", days: 30 },
  { key: "60", label: "60d", days: 60 },
  { key: "all", label: "All", days: null },
];
const DEFAULT_RANGE = "60";
const RANGE_COOKIE = "tank_range";

const TANK_ENHANCED_DAYS = 60;
const TEMP_OK_MIN_C = 0;
const TEMP_OK_MAX_C = 45;

// Approximate pixel height of the divider lightweight-charts draws between
// stacked panes — used to convert a lower pane's own-coordinate y position
// (from priceToCoordinate) into a position relative to the whole container.
const PANE_SEPARATOR = 6;

const MOBILE_QUERY = window.matchMedia("(max-width: 640px)");

// Each group is one lightweight-charts instance with two stacked panes
// sharing a time axis (and therefore zoom/pan + crosshair), but each pane
// keeps its own independent price scale — no dual-axis overlap. Zooming is
// independent between the two groups, since they're separate chart instances.
const GROUP_DEFS = {
  levelTemp: {
    containerId: "level-temp-chart",
    cardId: "level-temp-chart-card",
    emptyId: "level-temp-empty-state",
    paneHeights: [360, 180],
    paneHeightsMobile: [280, 140],
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
    paneHeights: [180, 180],
    paneHeightsMobile: [140, 140],
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
};

const state = {
  groups: {},
  tableVisible: false,
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

function baseChartOptions() {
  const gridline = cssVar("--gridline");
  const axis = cssVar("--axis");
  const surface = cssVar("--surface");
  const muted = cssVar("--text-muted");

  return {
    autoSize: true,
    layout: {
      background: { type: "solid", color: surface },
      textColor: muted,
      fontSize: 12,
      attributionLogo: false,
      panes: {
        separatorColor: gridline,
        separatorHoverColor: gridline,
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
    timeScale: {
      borderColor: axis,
      timeVisible: true,
      secondsVisible: false,
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
  for (const [key, def] of Object.entries(GROUP_DEFS)) {
    const group = state.groups[key];
    const heights = mobile ? def.paneHeightsMobile : def.paneHeights;
    heights.forEach((height, i) => group.chart.panes()[i].setHeight(height));
  }
}

function initGroupCharts() {
  for (const [key, def] of Object.entries(GROUP_DEFS)) {
    state.groups[key] = createGroupChart(def);
  }
  applyPaneHeights();
  MOBILE_QUERY.addEventListener("change", applyPaneHeights);
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

function updateGroupChart(key, readings) {
  const def = GROUP_DEFS[key];
  const group = state.groups[key];
  let anyPoints = false;

  for (const sdef of def.series) {
    const entry = group.seriesEntries[sdef.key];
    const points = pointsFor(readings, sdef.extract);
    entry.points = points;
    entry.pointsMap = new Map(points.map((p) => [p.time, p.value]));
    entry.series.setData(points);
    if (points.length) anyPoints = true;
  }

  group.chart.timeScale().fitContent();
  document.getElementById(def.emptyId).style.display = anyPoints ? "none" : "flex";
}

function renderSummary(data) {
  document.getElementById("last-reading").textContent = data.last_reading_time
    ? `Last reading: ${fmtTime(data.last_reading_time)}`
    : "Last reading: —";

  document.getElementById("stat-level").textContent = data.level_cm !== null ? fmtNumber(data.level_cm, 1) : "—";
  document.getElementById("stat-distance").textContent =
    data.distance_cm !== null && data.distance_cm !== undefined
      ? `sensor to water-surface ≈ ${fmtNumber(data.distance_cm, 1)} cm`
      : "sensor to water-surface = —";

  const emptyDateEl = document.getElementById("stat-empty-date");
  if (data.tank_empty_date) {
    emptyDateEl.textContent = `Estimated empty date: ${fmtDateOnly(data.tank_empty_date)}`;
    emptyDateEl.classList.toggle("enhanced", data.tank_empty_days !== null && data.tank_empty_days <= TANK_ENHANCED_DAYS);
  } else {
    emptyDateEl.textContent = "Estimated empty date: —";
    emptyDateEl.classList.remove("enhanced");
  }

  document.getElementById("stat-temp").textContent = data.chip_temp_c !== null ? fmtNumber(data.chip_temp_c, 1) : "—";
  const tempStatusEl = document.getElementById("stat-temp-status");
  tempStatusEl.classList.remove("status-good", "status-warning");
  if (data.chip_temp_c !== null && data.chip_temp_c !== undefined) {
    const inRange = data.chip_temp_c >= TEMP_OK_MIN_C && data.chip_temp_c <= TEMP_OK_MAX_C;
    tempStatusEl.textContent = inRange ? "Optimal operating range" : "Outside optimal range";
    tempStatusEl.classList.add(inRange ? "status-good" : "status-warning");
  } else {
    tempStatusEl.textContent = "—";
  }

  document.getElementById("stat-battery").textContent = data.battery_v !== null ? `${fmtNumber(data.battery_v, 2)} V` : "—";
  document.getElementById("stat-battery-recharge").textContent = data.battery_critical_date
    ? `Est. recharge by: ${fmtDateOnly(data.battery_critical_date)}`
    : "Est. recharge: —";
  const rssiEl = document.getElementById("stat-rssi");
  rssiEl.textContent = data.rssi !== null && data.rssi !== undefined ? `${fmtNumber(data.rssi)} dBm` : "—";
  rssiEl.classList.toggle("status-warning", Boolean(data.weak_signal_warning));
}

function renderUnifiedTable(readings) {
  const tbody = document.getElementById("unified-table-body");
  tbody.innerHTML = "";
  for (const r of [...readings].reverse()) {
    const tr = document.createElement("tr");
    const cells = [
      fmtTime(r.time),
      r.level_cm !== null ? fmtNumber(r.level_cm, 1) : "no echo",
      r.volume_liters !== null ? fmtNumber(r.volume_liters) : "—",
      r.chip_temp_c !== null ? fmtNumber(r.chip_temp_c, 1) : "—",
      fmtNumber(r.battery_mv / 1000, 2),
      r.rssi !== null ? fmtNumber(r.rssi) : "—",
    ];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

async function loadRange(presetKey) {
  const preset = RANGE_PRESETS.find((p) => p.key === presetKey) || RANGE_PRESETS.find((p) => p.key === DEFAULT_RANGE);

  document.querySelectorAll("#range-pills button[data-range]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.range === preset.key);
  });
  setCookie(RANGE_COOKIE, preset.key);

  const params = new URLSearchParams();
  const start = rangeStartIso(preset.days);
  if (start) params.set("start", start);

  const res = await fetch(`/watertank/api/readings?${params.toString()}`);
  const data = await res.json();

  for (const key of Object.keys(GROUP_DEFS)) {
    updateGroupChart(key, data.readings);
  }

  renderUnifiedTable(data.readings);
}

async function loadSummary() {
  const res = await fetch("/watertank/api/summary");
  const data = await res.json();
  renderSummary(data);
}

function initRangePills() {
  document.querySelectorAll("#range-pills button[data-range]").forEach((btn) => {
    btn.addEventListener("click", () => loadRange(btn.dataset.range));
  });
}

function initTableToggle() {
  const toggle = document.querySelector('.table-toggle[data-toggle="all"]');
  const tableWrap = document.getElementById("unified-table-wrap");
  const cardIds = Object.values(GROUP_DEFS).map((def) => def.cardId);
  toggle.addEventListener("click", () => {
    state.tableVisible = !state.tableVisible;
    tableWrap.style.display = state.tableVisible ? "block" : "none";
    for (const id of cardIds) {
      document.getElementById(id).style.display = state.tableVisible ? "none" : "block";
    }
    toggle.textContent = state.tableVisible ? "View as chart" : "View as table";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initGroupCharts();
  initRangePills();
  initTableToggle();
  const savedRange = getCookie(RANGE_COOKIE) || DEFAULT_RANGE;
  loadRange(savedRange);
  loadSummary();
});
