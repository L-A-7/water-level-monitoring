const RANGES = { "24h": 1, "7": 7, "30": 30, "60": 60, all: null };
const DEFAULT_RANGE = "7";
const CONFIRM_TIMEOUT_MS = 4000;

let readings = [];
let dataBounds = { start: null, end: null };
let selectedIds = new Set();
let anchorIndex = null;
let activeIndex = null;
let confirmTimer = null;

function fmtTime(iso) {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtNumber(n, decimals = 0) {
  return n === null || n === undefined ? "—" : Number(n).toFixed(decimals);
}

async function fetchReadings(start, end) {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const qs = params.toString();
  const res = await fetch(`/watertank/api/admin/edit-readings${qs ? `?${qs}` : ""}`);
  return res.json();
}

async function loadRange(rangeKey) {
  document.querySelectorAll("#editor-range-pills button[data-range]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.range === rangeKey);
  });

  let data;
  if (rangeKey === DEFAULT_RANGE || !dataBounds.end) {
    data = await fetchReadings();
  } else {
    const days = RANGES[rangeKey];
    const end = dataBounds.end;
    const start = days === null ? dataBounds.start : new Date(new Date(end).getTime() - days * 86400000).toISOString();
    data = await fetchReadings(start, end);
  }

  dataBounds = { start: data.data_start, end: data.data_end };
  readings = data.readings;
  selectedIds.clear();
  anchorIndex = null;
  activeIndex = null;
  renderTable();
}

function rowSelectedFields() {
  if (document.getElementById("erase-whole-reading").checked) return ["whole_reading"];
  const fields = [];
  if (document.getElementById("erase-water-level").checked) fields.push("water_level");
  if (document.getElementById("erase-temperature").checked) fields.push("temperature");
  return fields;
}

function eraseButtonLabel() {
  return rowSelectedFields().includes("whole_reading") ? "Delete selected reading(s)" : "Erase selected field(s)";
}

// "Whole reading" wipes everything on the row, so it doesn't make sense to
// combine with the column-level checkboxes -- keep them mutually exclusive.
function onWholeReadingChange() {
  const whole = document.getElementById("erase-whole-reading").checked;
  const waterCb = document.getElementById("erase-water-level");
  const tempCb = document.getElementById("erase-temperature");
  waterCb.disabled = whole;
  tempCb.disabled = whole;
  if (whole) {
    waterCb.checked = false;
    tempCb.checked = false;
  }
  updateToolbar();
}

function updateToolbar() {
  const count = selectedIds.size;
  document.getElementById("editor-status").textContent = count === 1 ? "1 selected" : `${count} selected`;
  const button = document.getElementById("erase-button");
  button.disabled = count === 0 || rowSelectedFields().length === 0;
  resetConfirm();
}

function resetConfirm() {
  clearTimeout(confirmTimer);
  confirmTimer = null;
  const button = document.getElementById("erase-button");
  button.classList.remove("confirm-pending");
  if (!button.disabled) {
    button.lastChild.textContent = eraseButtonLabel();
  }
}

function renderTable() {
  const tbody = document.getElementById("editor-table-body");
  const emptyState = document.getElementById("editor-empty-state");
  tbody.innerHTML = "";
  emptyState.style.display = readings.length ? "none" : "block";

  readings.forEach((r, idx) => {
    const tr = document.createElement("tr");
    tr.dataset.index = String(idx);
    tr.dataset.id = String(r.id);
    tr.tabIndex = -1;
    if (selectedIds.has(r.id)) tr.classList.add("selected");
    if (idx === activeIndex) tr.classList.add("active-row");

    const cells = [
      fmtTime(r.time),
      r.distance_cm !== null && r.distance_cm !== undefined ? fmtNumber(r.distance_cm, 1) : "no echo",
      fmtNumber(r.distance_std_cm, 2),
      fmtNumber(r.chip_temp_c, 1),
      fmtNumber(r.battery_mv, 0),
      fmtNumber(r.rssi, 0),
    ];
    for (const text of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }

    tr.addEventListener("click", (event) => onRowClick(idx, event));
    tbody.appendChild(tr);
  });

  updateToolbar();
}

function selectRange(fromIdx, toIdx) {
  const [lo, hi] = fromIdx <= toIdx ? [fromIdx, toIdx] : [toIdx, fromIdx];
  selectedIds.clear();
  for (let i = lo; i <= hi; i++) selectedIds.add(readings[i].id);
}

function onRowClick(idx, event) {
  document.getElementById("editor-table-wrap").focus();
  if (event.shiftKey && anchorIndex !== null) {
    selectRange(anchorIndex, idx);
  } else if (event.ctrlKey || event.metaKey) {
    const id = readings[idx].id;
    if (selectedIds.has(id)) selectedIds.delete(id);
    else selectedIds.add(id);
    anchorIndex = idx;
  } else {
    selectedIds = new Set([readings[idx].id]);
    anchorIndex = idx;
  }
  activeIndex = idx;
  renderTable();
  document.querySelector(`#editor-table-body tr[data-index="${idx}"]`)?.scrollIntoView({ block: "nearest" });
}

function onTableKeydown(event) {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  if (!readings.length) return;
  event.preventDefault();

  const delta = event.key === "ArrowDown" ? 1 : -1;
  const base = activeIndex === null ? (delta > 0 ? -1 : 0) : activeIndex;
  const nextIndex = Math.min(Math.max(base + delta, 0), readings.length - 1);

  if (event.shiftKey) {
    if (anchorIndex === null) anchorIndex = activeIndex ?? nextIndex;
    selectRange(anchorIndex, nextIndex);
  } else {
    selectedIds = new Set([readings[nextIndex].id]);
    anchorIndex = nextIndex;
  }
  activeIndex = nextIndex;
  renderTable();
  document.querySelector(`#editor-table-body tr[data-index="${nextIndex}"]`)?.scrollIntoView({ block: "nearest" });
}

async function onEraseClick() {
  const button = document.getElementById("erase-button");
  if (!button.classList.contains("confirm-pending")) {
    button.classList.add("confirm-pending");
    button.lastChild.textContent = "Click again to confirm";
    confirmTimer = setTimeout(resetConfirm, CONFIRM_TIMEOUT_MS);
    return;
  }

  resetConfirm();
  const ids = [...selectedIds];
  const fields = rowSelectedFields();
  if (!ids.length || !fields.length) return;

  button.disabled = true;
  try {
    const res = await fetch("/watertank/api/admin/erase-fields", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, fields }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const idSet = new Set(ids);
    const wholeReading = fields.includes("whole_reading");
    if (wholeReading) {
      readings = readings.filter((r) => !idSet.has(r.id));
    } else {
      for (const r of readings) {
        if (!idSet.has(r.id)) continue;
        if (fields.includes("water_level")) {
          r.distance_cm = null;
          r.distance_std_cm = null;
        }
        if (fields.includes("temperature")) r.chip_temp_c = null;
      }
    }
    selectedIds.clear();
    anchorIndex = null;
    activeIndex = null;
    renderTable();
    // after renderTable(), since updateToolbar() (called from within it)
    // would otherwise immediately overwrite this with "0 selected"
    document.getElementById("editor-status").textContent = wholeReading ? "Deleted." : "Erased.";
  } catch (err) {
    updateToolbar();
    document.getElementById("editor-status").textContent = "Failed to erase — try again.";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("#editor-range-pills button[data-range]").forEach((btn) => {
    btn.addEventListener("click", () => loadRange(btn.dataset.range));
  });
  document.getElementById("erase-water-level").addEventListener("change", updateToolbar);
  document.getElementById("erase-temperature").addEventListener("change", updateToolbar);
  document.getElementById("erase-whole-reading").addEventListener("change", onWholeReadingChange);
  document.getElementById("erase-button").addEventListener("click", onEraseClick);
  document.getElementById("editor-table-wrap").addEventListener("keydown", onTableKeydown);

  loadRange(DEFAULT_RANGE);
});
