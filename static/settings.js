document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("settings-form");
  if (!form) {
    return;
  }
  const startupToggle = form.elements.namedItem("use_startup_volume");
  const startupInput = form.elements.namedItem("startup_volume");
  const startupRow = form.querySelector("[data-startup-volume-row]");
  const statusNode = document.getElementById("settings-save-status");
  const sleepRotationButton = document.querySelector("[data-sleep-rotation-info]");
  const sleepRotationDialog = document.querySelector("[data-sleep-rotation-dialog]");

  let saveTimer = null;
  let inFlight = false;
  let pending = false;

  function syncStartupVolumeState() {
    if (!(startupToggle instanceof HTMLInputElement) || !(startupInput instanceof HTMLInputElement)) {
      return;
    }
    startupInput.disabled = !startupToggle.checked;
    if (startupRow instanceof HTMLElement) {
      startupRow.classList.toggle("is-disabled", !startupToggle.checked);
    }
  }

  function collectPayload() {
    const formData = new FormData(form);
    return Object.fromEntries(formData.entries());
  }

  function setStatus(message, tone = "neutral") {
    if (!(statusNode instanceof HTMLElement)) {
      return;
    }
    statusNode.textContent = message || "";
    statusNode.dataset.tone = tone;
  }

  async function saveSettings() {
    if (inFlight) {
      pending = true;
      return;
    }

    inFlight = true;
    pending = false;
    const payload = collectPayload();
    setStatus("Einstellungen werden gespeichert …", "busy");

    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok === false) {
        setStatus(result?.error || result?.message || "Einstellungen konnten nicht gespeichert werden.", "error");
        return;
      }
      setStatus(result.message || "Einstellungen gespeichert.", "success");
    } catch (_error) {
      setStatus("Einstellungen konnten nicht gespeichert werden.", "error");
    } finally {
      syncStartupVolumeState();
      inFlight = false;
      if (pending) {
        window.setTimeout(saveSettings, 0);
      }
    }
  }

  function scheduleSave() {
    if (saveTimer) {
      window.clearTimeout(saveTimer);
    }
    saveTimer = window.setTimeout(saveSettings, 120);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
  });

  syncStartupVolumeState();
  if (startupToggle instanceof HTMLInputElement) {
    startupToggle.addEventListener("change", syncStartupVolumeState);
  }
  form.addEventListener("change", scheduleSave);
  form.addEventListener("input", (event) => {
    if (event.target instanceof HTMLInputElement && event.target.type === "number") {
      scheduleSave();
    }
  });

  setStatus("Änderungen werden automatisch gespeichert.");

  if (sleepRotationButton instanceof HTMLButtonElement && sleepRotationDialog instanceof HTMLDialogElement) {
    sleepRotationButton.addEventListener("click", () => sleepRotationDialog.showModal());
  }
});
