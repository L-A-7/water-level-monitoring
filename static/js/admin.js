function parseOverride(value) {
  return value.trim() === "" ? null : Number(value);
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
}

async function submitAdminConfig(event) {
  event.preventDefault();
  const status = document.getElementById("config-status");
  status.textContent = "Saving…";
  status.className = "config-status";

  const body = {
    wakeup_period_min: parseOverride(document.getElementById("wakeup-period").value),
    avg_sample_count: parseOverride(document.getElementById("avg-sample-count").value),
  };

  try {
    const res = await fetch("/watertank/api/admin/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    status.textContent = "Saved.";
    status.className = "config-status success";
  } catch (err) {
    status.textContent = "Failed to save — check the values and try again.";
    status.className = "config-status error";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadAdminConfig();
  document.getElementById("config-form").addEventListener("submit", submitAdminConfig);
});
