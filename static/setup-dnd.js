document.addEventListener("DOMContentLoaded", () => {
  let draggedFunction = "";
  let selectedChip = null;
  let detectPollTimer = null;

  function emptyLabel(slot) {
    return slot.dataset.emptyLabel || "Funktion hierhin ziehen";
  }

  function applyToSlot(slot, value) {
    const hidden = slot.querySelector("input[type='hidden']");
    const label = slot.querySelector("[data-drop-label]");
    if (hidden) {
      hidden.value = value;
    }
    if (label) {
      label.textContent = value || emptyLabel(slot);
    }
  }

  function clearSelectedChip() {
    if (selectedChip) {
      selectedChip.classList.remove("selected");
      selectedChip = null;
    }
  }

  for (const chip of document.querySelectorAll("[data-function-chip]")) {
    chip.addEventListener("dragstart", (event) => {
      draggedFunction = chip.dataset.functionChip || "";
      event.dataTransfer?.setData("text/plain", draggedFunction);
    });

    chip.addEventListener("click", () => {
      if (selectedChip === chip) {
        clearSelectedChip();
        draggedFunction = "";
        return;
      }
      clearSelectedChip();
      selectedChip = chip;
      draggedFunction = chip.dataset.functionChip || "";
      chip.classList.add("selected");
    });
  }

  for (const slot of document.querySelectorAll("[data-drop-slot]")) {
    slot.addEventListener("dragover", (event) => {
      event.preventDefault();
      slot.classList.add("drag-over");
    });

    slot.addEventListener("dragleave", () => {
      slot.classList.remove("drag-over");
    });

    slot.addEventListener("drop", (event) => {
      event.preventDefault();
      const dropped = event.dataTransfer?.getData("text/plain") || draggedFunction;
      applyToSlot(slot, dropped);
      slot.classList.remove("drag-over");
      clearSelectedChip();
    });

    slot.addEventListener("click", () => {
      if (!draggedFunction) {
        return;
      }
      applyToSlot(slot, draggedFunction);
      clearSelectedChip();
      draggedFunction = "";
    });

    slot.addEventListener("dblclick", () => {
      applyToSlot(slot, "");
    });
  }

  const detectRoot = document.querySelector("[data-button-detect]");
  if (detectRoot) {
    const detectStart = detectRoot.querySelector("[data-detect-start]");
    const detectResult = detectRoot.querySelector("[data-detect-result]");
    const detectTimer = detectRoot.querySelector("[data-detect-timer]");

    function stopDetectPolling() {
      if (detectPollTimer) {
        window.clearTimeout(detectPollTimer);
        detectPollTimer = null;
      }
    }

    function renderDetectState(payload) {
      const status = payload.status || "idle";
      if (detectResult) {
        if (status === "detected") {
          detectResult.textContent = payload.message || "-";
        } else if (status === "listening") {
          detectResult.textContent = "Warte auf Tastendruck...";
        } else if (status === "timeout") {
          detectResult.textContent = "Keine Taste erkannt";
        } else if (status === "unavailable") {
          detectResult.textContent = payload.message || "Tasterkennung nicht verfügbar";
        } else {
          detectResult.textContent = "-";
        }
      }

      if (detectTimer) {
        if (status === "listening") {
          detectTimer.hidden = false;
          detectTimer.textContent = `Erkennung aktiv: ${payload.remaining_seconds || 0}s`;
        } else {
          detectTimer.hidden = true;
          detectTimer.textContent = "";
        }
      }

      if (detectStart instanceof HTMLButtonElement) {
        detectStart.disabled = status === "listening";
      }
    }

    async function pollDetectStatus() {
      try {
        const response = await fetch("/api/setup/button-detect/status");
        const payload = await response.json();
        renderDetectState(payload);
        if (payload.status === "listening") {
          detectPollTimer = window.setTimeout(pollDetectStatus, 250);
          return;
        }
      } catch {
        if (detectResult) {
          detectResult.textContent = "Tasterkennung fehlgeschlagen";
        }
      }
      stopDetectPolling();
    }

    if (detectStart instanceof HTMLButtonElement) {
      detectStart.addEventListener("click", async () => {
        stopDetectPolling();
        try {
          const response = await fetch("/api/setup/button-detect/start", {method: "POST"});
          const payload = await response.json();
          renderDetectState(payload);
          if (response.ok && payload.status === "listening") {
            detectPollTimer = window.setTimeout(pollDetectStatus, 250);
          }
        } catch {
          if (detectResult) {
            detectResult.textContent = "Tasterkennung fehlgeschlagen";
          }
          if (detectTimer) {
            detectTimer.hidden = true;
          }
          detectStart.disabled = false;
        }
      });
    }
  }

  const buttonMapping = document.querySelector("[data-button-mapping]");
  if (buttonMapping) {
    const rows = Array.from(buttonMapping.querySelectorAll(".mapping-row"));

    function syncPressTypeChoices() {
      for (const row of rows) {
        const pinSelect = row.querySelector("[data-button-pin]");
        const pressSelect = row.querySelector("[data-button-press-type]");
        if (!(pinSelect instanceof HTMLSelectElement) || !(pressSelect instanceof HTMLSelectElement)) {
          continue;
        }

        const currentPin = pinSelect.value;
        const currentValue = pressSelect.value || "kurz";
        const usedPressTypes = new Set();

        for (const otherRow of rows) {
          if (otherRow === row) {
            continue;
          }
          const otherPin = otherRow.querySelector("[data-button-pin]");
          const otherPress = otherRow.querySelector("[data-button-press-type]");
          if (!(otherPin instanceof HTMLSelectElement) || !(otherPress instanceof HTMLSelectElement)) {
            continue;
          }
          if (otherPin.value && otherPin.value === currentPin) {
            usedPressTypes.add(otherPress.value || "kurz");
          }
        }

        const allowed = ["kurz", "lang"].filter((option) => !usedPressTypes.has(option));
        const fallback = allowed[0] || "kurz";

        for (const option of pressSelect.options) {
          option.hidden = !allowed.includes(option.value);
          option.disabled = !allowed.includes(option.value);
        }

        if (!allowed.includes(currentValue)) {
          pressSelect.value = fallback;
        }
      }
    }

    for (const row of rows) {
      const pinSelect = row.querySelector("[data-button-pin]");
      const pressSelect = row.querySelector("[data-button-press-type]");
      pinSelect?.addEventListener("change", syncPressTypeChoices);
      pressSelect?.addEventListener("change", syncPressTypeChoices);
    }

    syncPressTypeChoices();
  }

  const hotspotSecurity = document.querySelector("[data-hotspot-security]");
  const hotspotPasswordField = document.querySelector("[data-hotspot-password-field]");
  if (hotspotSecurity instanceof HTMLSelectElement && hotspotPasswordField instanceof HTMLElement) {
    const hotspotPasswordInput = hotspotPasswordField.querySelector("input[name='hotspot_password']");

    function syncHotspotPasswordField() {
      if (!(hotspotPasswordInput instanceof HTMLInputElement)) {
        return;
      }
      hotspotPasswordInput.disabled = hotspotSecurity.value !== "wpa-psk";
    }

    hotspotSecurity.addEventListener("change", syncHotspotPasswordField);
    syncHotspotPasswordField();
  }

  const audioTestButton = document.querySelector("[data-audio-test-button]");
  if (audioTestButton instanceof HTMLButtonElement) {
    audioTestButton.addEventListener("click", async () => {
      audioTestButton.disabled = true;
      const originalLabel = audioTestButton.textContent;
      audioTestButton.textContent = "Spielt...";
      try {
        await fetch("/api/runtime/audio-test", {method: "POST"});
      } finally {
        audioTestButton.disabled = false;
        audioTestButton.textContent = originalLabel;
      }
    });
  }
});
