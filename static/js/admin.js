function fmtTime(iso) {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function parseOverride(value) {
  return value.trim() === "" ? null : Number(value);
}

const SLIDERS = [
  { input: "low-level-threshold", output: "low-level-value", decimals: 0 },
  { input: "low-battery-threshold", output: "low-battery-value", decimals: 1 },
  { input: "weak-signal-threshold", output: "weak-signal-value", decimals: 0 },
  { input: "submersed-threshold", output: "submersed-value", decimals: 0 },
];

function initSliders() {
  for (const { input, output, decimals } of SLIDERS) {
    const inputEl = document.getElementById(input);
    const outputEl = document.getElementById(output);
    inputEl.addEventListener("input", () => {
      outputEl.textContent = Number(inputEl.value).toFixed(decimals);
    });
  }
}

async function loadAdminConfig() {
  const res = await fetch("/watertank/api/admin/config");
  const data = await res.json();

  const reportedBody = document.getElementById("device-reported-body");
  const reported = data.device_reported;
  if (reported) {
    reportedBody.textContent =
      `${fmtTime(reported.received_at)} — wakeup ${reported.wakeup_period_min} min, ` +
      `avg ${reported.avg_sample_count} samples, RSSI ${reported.rssi} dBm`;
  } else {
    reportedBody.textContent = "No device check-in recorded yet.";
  }

  document.getElementById("wakeup-period").value = data.desired.wakeup_period_min ?? "";
  document.getElementById("avg-sample-count").value = data.desired.avg_sample_count ?? "";
  document.getElementById("reference-offset").value = data.calibration.reference_offset_cm;
  document.getElementById("temp-offset").value = data.calibration.chip_temp_offset_c;
}

async function loadAdminAlerts() {
  const res = await fetch("/watertank/api/admin/alerts");
  const data = await res.json();

  document.getElementById("low-level-threshold").value = data.low_level_threshold_cm;
  document.getElementById("low-level-value").textContent = Number(data.low_level_threshold_cm).toFixed(0);

  document.getElementById("low-battery-threshold").value = data.low_battery_threshold_v;
  document.getElementById("low-battery-value").textContent = Number(data.low_battery_threshold_v).toFixed(1);

  document.getElementById("weak-signal-threshold").value = data.weak_signal_threshold_dbm;
  document.getElementById("weak-signal-value").textContent = Number(data.weak_signal_threshold_dbm).toFixed(0);

  document.getElementById("submersed-threshold").value = data.submersed_threshold_cm;
  document.getElementById("submersed-value").textContent = Number(data.submersed_threshold_cm).toFixed(0);

  document.getElementById("recipient-email").value = data.recipient_email ?? "";
  document.getElementById("sub-low-level").checked = data.subscribe_critical_low_level;
  document.getElementById("sub-low-battery").checked = data.subscribe_low_battery;
  document.getElementById("sub-submersion-risk").checked = data.subscribe_submersion_risk;
}

async function submitAdminConfig(event) {
  event.preventDefault();
  const status = document.getElementById("config-status");
  status.textContent = "Saving…";
  status.className = "config-status";

  const configBody = {
    wakeup_period_min: parseOverride(document.getElementById("wakeup-period").value),
    avg_sample_count: parseOverride(document.getElementById("avg-sample-count").value),
    reference_offset_cm: Number(document.getElementById("reference-offset").value),
    chip_temp_offset_c: Number(document.getElementById("temp-offset").value),
  };

  const alertsBody = {
    low_level_threshold_cm: Number(document.getElementById("low-level-threshold").value),
    low_battery_threshold_v: Number(document.getElementById("low-battery-threshold").value),
    weak_signal_threshold_dbm: Number(document.getElementById("weak-signal-threshold").value),
    submersed_threshold_cm: Number(document.getElementById("submersed-threshold").value),
    recipient_email: document.getElementById("recipient-email").value.trim() || null,
    subscribe_critical_low_level: document.getElementById("sub-low-level").checked,
    subscribe_low_battery: document.getElementById("sub-low-battery").checked,
    subscribe_submersion_risk: document.getElementById("sub-submersion-risk").checked,
  };

  try {
    const [configRes, alertsRes] = await Promise.all([
      fetch("/watertank/api/admin/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(configBody),
      }),
      fetch("/watertank/api/admin/alerts", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(alertsBody),
      }),
    ]);
    if (!configRes.ok || !alertsRes.ok) throw new Error(`HTTP ${configRes.status}/${alertsRes.status}`);
    status.textContent = "Saved.";
    status.className = "config-status success";
  } catch (err) {
    status.textContent = "Failed to save — check the values and try again.";
    status.className = "config-status error";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initSliders();
  loadAdminConfig();
  loadAdminAlerts();
  document.getElementById("config-form").addEventListener("submit", submitAdminConfig);
});
