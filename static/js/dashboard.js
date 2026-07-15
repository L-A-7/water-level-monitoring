const RANGE_PRESETS = [
  { key: "7", label: "7d", days: 7 },
  { key: "30", label: "30d", days: 30 },
  { key: "60", label: "60d", days: 60 },
  { key: "all", label: "All", days: null },
];
const DEFAULT_RANGE = "60";

const TANK_ENHANCED_DAYS = 60;
const BATTERY_ENHANCED_DAYS = 7;

const sections = {
  level: { cookie: "tank_range_level", tableVisible: false, chart: null },
  battery: { cookie: "tank_range_battery", tableVisible: false, chart: null },
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
  d.setDate(d.getDate() - days);
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

function baseChartOptions(yTitle) {
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
      },
    },
    scales: {
      x: {
        type: "time",
        grid: { color: gridline, drawTicks: false },
        ticks: { color: muted, maxRotation: 0 },
        border: { color: axis },
      },
      y: {
        title: { display: true, text: yTitle, color: muted, font: { size: 12 } },
        grid: { color: gridline, drawTicks: false },
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

  const points = readings
    .filter((r) => r.level_cm !== null)
    .map((r) => ({ x: r.time, y: r.level_cm, volume: r.volume_liters, battery: r.battery_mv }));

  if (!points.length) {
    chartCard.style.display = "none";
    emptyState.style.display = "block";
    return;
  }
  chartCard.style.display = sections.level.tableVisible ? "none" : "block";
  emptyState.style.display = "none";

  const seriesColor = cssVar("--series-1");
  const wash = cssVar("--series-1-wash");
  const surface = cssVar("--surface");

  if (sections.level.chart) {
    sections.level.chart.destroy();
  }

  const options = baseChartOptions("Level (cm)");
  options.plugins.tooltip.callbacks = {
    title(items) {
      return fmtTime(items[0].raw.x);
    },
    label(item) {
      const raw = item.raw;
      const lines = [`Level: ${fmtNumber(raw.y, 1)} cm`];
      if (raw.volume !== null && raw.volume !== undefined) {
        lines.push(`Volume: ~${fmtNumber(raw.volume)} L`);
      }
      if (raw.battery !== null && raw.battery !== undefined) {
        lines.push(`Battery: ${fmtNumber(raw.battery / 1000, 2)} V`);
      }
      return lines;
    },
  };

  sections.level.chart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      datasets: [
        {
          label: "Water level",
          data: points,
          borderColor: seriesColor,
          backgroundColor: wash,
          borderWidth: 2,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: seriesColor,
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

  const points = readings.map((r) => ({ x: r.time, y: r.battery_mv / 1000 }));

  if (!points.length) {
    chartCard.style.display = "none";
    return;
  }
  chartCard.style.display = sections.battery.tableVisible ? "none" : "block";

  const seriesColor = cssVar("--series-2");
  const wash = cssVar("--series-2-wash");
  const surface = cssVar("--surface");

  if (sections.battery.chart) {
    sections.battery.chart.destroy();
  }

  const options = baseChartOptions("Battery (V)");
  options.plugins.tooltip.callbacks = {
    title(items) {
      return fmtTime(items[0].raw.x);
    },
    label(item) {
      return `Battery: ${fmtNumber(item.raw.y, 2)} V`;
    },
  };

  sections.battery.chart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      datasets: [
        {
          label: "Battery voltage",
          data: points,
          borderColor: seriesColor,
          backgroundColor: wash,
          borderWidth: 2,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: seriesColor,
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

function renderSummary(data) {
  document.getElementById("last-reading").textContent = data.last_reading_time
    ? `Last reading: ${fmtTime(data.last_reading_time)}`
    : "Last reading: —";

  document.getElementById("stat-level").textContent =
    data.level_cm !== null ? `${fmtNumber(data.level_cm, 1)} cm` : "—";
  document.getElementById("stat-volume").textContent =
    data.volume_m3 !== null ? `~${fmtNumber(data.volume_m3, 2)} m³` : "—";
  document.getElementById("stat-battery").textContent =
    data.battery_v !== null ? `${fmtNumber(data.battery_v, 2)} V` : "—";

  const emptyDateEl = document.getElementById("stat-empty-date");
  if (data.tank_empty_date) {
    emptyDateEl.textContent = fmtDateOnly(data.tank_empty_date);
    emptyDateEl.classList.toggle("enhanced", data.tank_empty_days !== null && data.tank_empty_days <= TANK_ENHANCED_DAYS);
  } else {
    emptyDateEl.textContent = "—";
    emptyDateEl.classList.remove("enhanced");
  }

  const batteryDaysEl = document.getElementById("stat-battery-days");
  if (data.battery_critical_days !== null && data.battery_critical_days !== undefined) {
    batteryDaysEl.textContent = `${fmtNumber(data.battery_critical_days)} days`;
    batteryDaysEl.classList.toggle("enhanced", data.battery_critical_days <= BATTERY_ENHANCED_DAYS);
  } else {
    batteryDaysEl.textContent = "—";
    batteryDaysEl.classList.remove("enhanced");
  }
}

function renderLevelTable(readings) {
  const tbody = document.getElementById("level-table-body");
  tbody.innerHTML = "";
  for (const r of [...readings].reverse()) {
    const tr = document.createElement("tr");
    const cells = [
      fmtTime(r.time),
      r.level_cm !== null ? fmtNumber(r.level_cm, 1) : "no echo",
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
    const cells = [fmtTime(r.time), fmtNumber(r.battery_mv / 1000, 2)];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

async function loadSectionRange(key, presetKey) {
  const preset = RANGE_PRESETS.find((p) => p.key === presetKey) || RANGE_PRESETS.find((p) => p.key === DEFAULT_RANGE);

  document.querySelectorAll(`.filter-row[data-chart="${key}"] button[data-range]`).forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.range === preset.key);
  });
  setCookie(sections[key].cookie, preset.key);

  const params = new URLSearchParams();
  const start = rangeStartIso(preset.days);
  if (start) params.set("start", start);

  const res = await fetch(`/watertank/api/readings?${params.toString()}`);
  const data = await res.json();

  if (key === "level") {
    renderLevelChart(data.readings);
    renderLevelTable(data.readings);
  } else {
    renderBatteryChart(data.readings);
    renderBatteryTable(data.readings);
  }
}

async function loadSummary() {
  const res = await fetch("/watertank/api/summary");
  const data = await res.json();
  renderSummary(data);
}

function initRangeButtons(key) {
  document.querySelectorAll(`.filter-row[data-chart="${key}"] button[data-range]`).forEach((btn) => {
    btn.addEventListener("click", () => loadSectionRange(key, btn.dataset.range));
  });
}

function initTableToggle(key) {
  const toggle = document.querySelector(`.table-toggle[data-toggle="${key}"]`);
  const tableWrap = document.getElementById(`${key}-table-wrap`);
  const chartCard = document.getElementById(`${key}-chart-card`);
  toggle.addEventListener("click", () => {
    sections[key].tableVisible = !sections[key].tableVisible;
    tableWrap.style.display = sections[key].tableVisible ? "block" : "none";
    chartCard.style.display = sections[key].tableVisible ? "none" : "block";
    toggle.textContent = sections[key].tableVisible ? "View as chart" : "View as table";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  for (const key of Object.keys(sections)) {
    initRangeButtons(key);
    initTableToggle(key);
    const savedRange = getCookie(sections[key].cookie) || DEFAULT_RANGE;
    loadSectionRange(key, savedRange);
  }
  loadSummary();
});
