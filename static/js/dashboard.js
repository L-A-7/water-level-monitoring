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

const state = {
  levelChart: null,
  batteryChart: null,
  levelTableVisible: false,
  batteryTableVisible: false,
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

const crosshairPlugin = {
  id: "crosshair",
  afterDraw(chartInstance) {
    const active = chartInstance.getActiveElements();
    if (!active || !active.length) return;
    const { ctx, chartArea } = chartInstance;
    const x = active[0].element.x;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.lineWidth = 1;
    ctx.strokeStyle = cssVar("--axis");
    ctx.stroke();
    ctx.restore();
  },
};

function dualAxisOptions(leftLabel, rightLabel) {
  const gridline = cssVar("--gridline");
  const muted = cssVar("--text-muted");
  const axis = cssVar("--axis");
  const surface = cssVar("--surface");
  const primary = cssVar("--text-primary");
  const secondary = cssVar("--text-secondary");

  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: surface,
        titleColor: secondary,
        bodyColor: primary,
        borderColor: gridline,
        borderWidth: 1,
        padding: 10,
        usePointStyle: true,
      },
    },
    scales: {
      x: {
        type: "time",
        grid: { color: gridline, drawTicks: false },
        ticks: { color: muted, maxRotation: 0, autoSkipPadding: 16 },
        border: { color: axis },
      },
      yLeft: {
        type: "linear",
        position: "left",
        title: { display: true, text: leftLabel, color: muted, font: { size: 12 } },
        grid: { color: gridline, drawTicks: false },
        ticks: { color: muted },
        border: { color: axis },
      },
      yRight: {
        type: "linear",
        position: "right",
        title: { display: true, text: rightLabel, color: muted, font: { size: 12 } },
        grid: { display: false },
        ticks: { color: muted },
        border: { color: axis },
      },
    },
  };
}

function renderLevelChart(readings) {
  const canvas = document.getElementById("level-chart");
  const emptyState = document.getElementById("empty-state");
  const chartCard = document.getElementById("level-chart-card");

  const levelPoints = readings.filter((r) => r.level_cm !== null).map((r) => ({ x: r.time, y: r.level_cm }));
  const tempPoints = readings.filter((r) => r.chip_temp_c !== null).map((r) => ({ x: r.time, y: r.chip_temp_c }));

  if (!levelPoints.length && !tempPoints.length) {
    chartCard.style.display = "none";
    emptyState.style.display = "block";
    return;
  }
  chartCard.style.display = state.levelTableVisible ? "none" : "block";
  emptyState.style.display = "none";

  const levelColor = cssVar("--series-1");
  const levelWash = cssVar("--series-1-wash");
  const tempColor = cssVar("--series-2");
  const surface = cssVar("--surface");

  if (state.levelChart) {
    state.levelChart.destroy();
  }

  const options = dualAxisOptions("Level (cm)", "Temp (°C)");
  options.plugins.tooltip.callbacks = {
    title(items) {
      return fmtTime(items[0].raw.x);
    },
    label(item) {
      if (item.dataset.yAxisID === "yLeft") return `Level: ${fmtNumber(item.raw.y, 1)} cm`;
      return `Temp: ${fmtNumber(item.raw.y, 1)} °C`;
    },
  };

  state.levelChart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      datasets: [
        {
          label: "Water level",
          yAxisID: "yLeft",
          data: levelPoints,
          borderColor: levelColor,
          backgroundColor: levelWash,
          borderWidth: 2,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: levelColor,
          pointHoverBorderColor: surface,
          pointHoverBorderWidth: 2,
          tension: 0.15,
        },
        {
          label: "Chip temperature",
          yAxisID: "yRight",
          data: tempPoints,
          borderColor: tempColor,
          backgroundColor: "transparent",
          borderWidth: 2,
          fill: false,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: tempColor,
          pointHoverBorderColor: surface,
          pointHoverBorderWidth: 2,
          tension: 0.15,
        },
      ],
    },
    options,
    plugins: [crosshairPlugin],
  });
}

function renderBatteryChart(readings) {
  const canvas = document.getElementById("battery-chart");
  const chartCard = document.getElementById("battery-chart-card");

  const batteryPoints = readings.map((r) => ({ x: r.time, y: r.battery_mv / 1000 }));
  const rssiPoints = readings.filter((r) => r.rssi !== null).map((r) => ({ x: r.time, y: r.rssi }));

  if (!batteryPoints.length) {
    chartCard.style.display = "none";
    return;
  }
  chartCard.style.display = state.batteryTableVisible ? "none" : "block";

  const batteryColor = cssVar("--series-3");
  const rssiColor = cssVar("--series-4");
  const surface = cssVar("--surface");

  if (state.batteryChart) {
    state.batteryChart.destroy();
  }

  const options = dualAxisOptions("Battery (V)", "RSSI (dBm)");
  options.plugins.tooltip.callbacks = {
    title(items) {
      return fmtTime(items[0].raw.x);
    },
    label(item) {
      if (item.dataset.yAxisID === "yLeft") return `Battery: ${fmtNumber(item.raw.y, 2)} V`;
      return `RSSI: ${fmtNumber(item.raw.y, 0)} dBm`;
    },
  };

  state.batteryChart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      datasets: [
        {
          label: "Battery voltage",
          yAxisID: "yLeft",
          data: batteryPoints,
          borderColor: batteryColor,
          backgroundColor: "transparent",
          borderWidth: 2,
          fill: false,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: batteryColor,
          pointHoverBorderColor: surface,
          pointHoverBorderWidth: 2,
          tension: 0.2,
        },
        {
          label: "Signal strength (RSSI)",
          yAxisID: "yRight",
          data: rssiPoints,
          borderColor: rssiColor,
          backgroundColor: "transparent",
          borderWidth: 2,
          borderDash: [4, 4],
          fill: false,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: rssiColor,
          pointHoverBorderColor: surface,
          pointHoverBorderWidth: 2,
          tension: 0.25,
          spanGaps: true,
        },
      ],
    },
    options,
    plugins: [crosshairPlugin],
  });
}

function renderSummary(data) {
  document.getElementById("last-reading").textContent = data.last_reading_time
    ? `Last reading: ${fmtTime(data.last_reading_time)}`
    : "Last reading: —";

  document.getElementById("stat-level").textContent = data.level_cm !== null ? fmtNumber(data.level_cm, 1) : "—";
  document.getElementById("stat-distance").textContent =
    data.level_cm !== null ? `sensor to water-surface ≈ ${fmtNumber(data.level_cm, 1)} cm` : "sensor to water-surface = —";

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

function renderLevelTable(readings) {
  const tbody = document.getElementById("level-table-body");
  tbody.innerHTML = "";
  for (const r of [...readings].reverse()) {
    const tr = document.createElement("tr");
    const cells = [
      fmtTime(r.time),
      r.level_cm !== null ? fmtNumber(r.level_cm, 1) : "no echo",
      r.chip_temp_c !== null ? fmtNumber(r.chip_temp_c, 1) : "—",
      r.volume_liters !== null ? fmtNumber(r.volume_liters) : "—",
    ];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function renderBatteryTable(readings) {
  const tbody = document.getElementById("battery-table-body");
  tbody.innerHTML = "";
  for (const r of [...readings].reverse()) {
    const tr = document.createElement("tr");
    const cells = [fmtTime(r.time), fmtNumber(r.battery_mv / 1000, 2), r.rssi !== null ? fmtNumber(r.rssi) : "—"];
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

  renderLevelChart(data.readings);
  renderLevelTable(data.readings);
  renderBatteryChart(data.readings);
  renderBatteryTable(data.readings);
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

function initTableToggle(key) {
  const toggle = document.querySelector(`.table-toggle[data-toggle="${key}"]`);
  const tableWrap = document.getElementById(`${key}-table-wrap`);
  const chartCard = document.getElementById(`${key}-chart-card`);
  const visibleKey = key === "level" ? "levelTableVisible" : "batteryTableVisible";
  toggle.addEventListener("click", () => {
    state[visibleKey] = !state[visibleKey];
    tableWrap.style.display = state[visibleKey] ? "block" : "none";
    chartCard.style.display = state[visibleKey] ? "none" : "block";
    toggle.textContent = state[visibleKey] ? "View as chart" : "View as table";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initRangePills();
  initTableToggle("level");
  initTableToggle("battery");
  const savedRange = getCookie(RANGE_COOKIE) || DEFAULT_RANGE;
  loadRange(savedRange);
  loadSummary();
});
