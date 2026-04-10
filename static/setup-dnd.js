document.addEventListener("DOMContentLoaded", () => {
  let draggedFunction = "";
  let selectedChip = null;
  let detectPollTimer = null;
  let readerRebootTimer = null;
  let readerInstallTimer = null;
  const readerRebootDialog = document.querySelector("[data-reader-reboot-dialog]");

  const readerForm = document.querySelector("[data-reader-form]");
  if (readerForm) {
    const installedReader = (readerForm.dataset.installedReader || "NONE").trim();
    const typeSelect = readerForm.querySelector("[data-reader-type-select]");
    const actionButton = readerForm.querySelector("[data-reader-action-button]");
    const actionInput = readerForm.querySelector("[data-reader-action-input]");
    const installBadge = readerForm.querySelector("[data-reader-install-badge]");
    const installed = installedReader !== "NONE";
    const countdownNode = readerRebootDialog instanceof HTMLDialogElement
      ? readerRebootDialog.querySelector("[data-reader-reboot-countdown]")
      : null;
    const titleNode = readerRebootDialog instanceof HTMLDialogElement
      ? readerRebootDialog.querySelector("[data-reader-reboot-title]")
      : null;
    const copyNode = readerRebootDialog instanceof HTMLDialogElement
      ? readerRebootDialog.querySelector("[data-reader-reboot-copy]")
      : null;
    const hintNode = readerRebootDialog instanceof HTMLDialogElement
      ? readerRebootDialog.querySelector("[data-reader-reboot-hint]")
      : null;
    const progressBar = readerRebootDialog instanceof HTMLDialogElement
      ? readerRebootDialog.querySelector("[data-reader-progress-bar]")
      : null;
    const progressLabel = readerRebootDialog instanceof HTMLDialogElement
      ? readerRebootDialog.querySelector("[data-reader-progress-label]")
      : null;
    const refreshButton = readerRebootDialog instanceof HTMLDialogElement
      ? readerRebootDialog.querySelector("[data-reader-reboot-refresh]")
      : null;

    function setReaderProgress(percent, {indeterminate = false, label = ""} = {}) {
      if (progressBar instanceof HTMLElement) {
        progressBar.style.width = `${Math.max(0, Math.min(percent, 100))}%`;
        progressBar.classList.toggle("is-indeterminate", indeterminate);
      }
      if (progressLabel instanceof HTMLElement && label) {
        progressLabel.textContent = label;
      }
    }

    function startReaderInstallOverlay(action) {
      if (!(readerRebootDialog instanceof HTMLDialogElement)) {
        return;
      }
      if (readerInstallTimer) {
        window.clearInterval(readerInstallTimer);
        readerInstallTimer = null;
      }
      if (titleNode instanceof HTMLElement) {
        titleNode.textContent = action === "uninstall" ? "Reader wird deinstalliert" : "Reader wird installiert";
      }
      if (countdownNode instanceof HTMLElement) {
        countdownNode.textContent = "Installation läuft";
      }
      if (copyNode instanceof HTMLElement) {
        copyNode.textContent = action === "uninstall"
          ? "Die Reader-Konfiguration wird entfernt. Abhängigkeiten und Systemzustand werden aktualisiert."
          : "Die Reader-Konfiguration wird eingerichtet. Abhängigkeiten und Systemzustand werden aktualisiert.";
      }
      if (hintNode instanceof HTMLElement) {
        hintNode.textContent = "Dieser Schritt kann etwas dauern.";
      }
      if (refreshButton instanceof HTMLButtonElement) {
        refreshButton.disabled = true;
      }
      if (countdownNode instanceof HTMLElement) {
        countdownNode.hidden = false;
      }
      let visualProgress = 12;
      setReaderProgress(visualProgress, {
        indeterminate: true,
        label: "Systemvoraussetzungen werden vorbereitet.",
      });
      readerRebootDialog.showModal();
      readerInstallTimer = window.setInterval(() => {
        visualProgress = Math.min(78, visualProgress + 4);
        setReaderProgress(visualProgress, {
          indeterminate: true,
          label: visualProgress < 40
            ? "Systemvoraussetzungen werden geprüft."
            : "Reader-Abhängigkeiten werden installiert.",
        });
      }, 900);
    }

    const syncReaderAction = () => {
      if (!(typeSelect instanceof HTMLSelectElement)) {
        return;
      }
      const selectedType = (typeSelect.value || "NONE").trim();
      if (actionInput instanceof HTMLInputElement) {
        actionInput.value = installed ? "uninstall" : "install";
      }
      if (installBadge instanceof HTMLElement) {
        installBadge.textContent = installed ? "Reader installiert" : "Kein Reader installiert";
        installBadge.classList.toggle("is-ready", installed);
        installBadge.classList.toggle("is-warning", !installed);
      }
      if (actionButton instanceof HTMLButtonElement) {
        actionButton.textContent = installed ? "Reader deinstallieren" : "Reader installieren";
        actionButton.classList.toggle("primary", !installed);
        actionButton.classList.toggle("danger", installed);
        actionButton.disabled = !installed && selectedType === "NONE";
      }
    };

    if (typeSelect instanceof HTMLSelectElement) {
      typeSelect.addEventListener("change", syncReaderAction);
    }
    if (actionButton instanceof HTMLButtonElement) {
      actionButton.addEventListener("click", (event) => {
        if (!installed) {
          return;
        }
        if (!window.confirm("Reader wirklich deinstallieren?")) {
          event.preventDefault();
        }
      });
    }
    readerForm.addEventListener("submit", () => {
      const action = actionInput instanceof HTMLInputElement ? (actionInput.value || "").trim() : "";
      if (!action) {
        return;
      }
      startReaderInstallOverlay(action);
    });
    syncReaderAction();
  }

  function emptyLabel(slot) {
    return slot.dataset.emptyLabel || "";
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
    const buttonPinSelects = rows
      .map((row) => row.querySelector("[data-button-pin]"))
      .filter((entry) => entry instanceof HTMLSelectElement);
    const buttonPressSelects = rows
      .map((row) => row.querySelector("[data-button-press-type]"))
      .filter((entry) => entry instanceof HTMLSelectElement);
    const ledPinSelects = Array.from(document.querySelectorAll("[data-led-pin]"))
      .filter((entry) => entry instanceof HTMLSelectElement);
    const hardwareButtonsToggle = buttonMapping.querySelector("[data-hardware-buttons-toggle]");
    const longPressInput = buttonMapping.querySelector("[data-button-long-press]");
    const longPressField = buttonMapping.querySelector(".long-press-field");

    function syncHardwareButtonAvailability() {
      const enabled = !(hardwareButtonsToggle instanceof HTMLInputElement) || hardwareButtonsToggle.checked;

      for (const row of rows) {
        row.classList.toggle("is-disabled", !enabled);
      }
      for (const select of buttonPinSelects) {
        select.disabled = !enabled;
      }
      for (const select of buttonPressSelects) {
        const locked = select.dataset.pressLocked === "1";
        select.disabled = !enabled || locked;
      }
      if (longPressInput instanceof HTMLInputElement) {
        longPressInput.disabled = !enabled;
      }
      if (longPressField instanceof HTMLElement) {
        longPressField.classList.toggle("is-disabled", !enabled);
      }
    }

    function syncPressTypeChoices() {
      for (const row of rows) {
        const pinSelect = row.querySelector("[data-button-pin]");
        const pressSelect = row.querySelector("[data-button-press-type]");
        if (!(pinSelect instanceof HTMLSelectElement) || !(pressSelect instanceof HTMLSelectElement)) {
          continue;
        }
        if (pressSelect.dataset.pressLocked === "1") {
          for (const option of pressSelect.options) {
            const keep = option.value === "lang";
            option.hidden = !keep;
            option.disabled = !keep;
          }
          pressSelect.value = "lang";
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

    function syncCrossRolePinChoices() {
      const selectedButtonPins = new Set(buttonPinSelects.map((select) => select.value).filter(Boolean));
      const selectedLedPins = new Set(ledPinSelects.map((select) => select.value).filter(Boolean));

      for (const select of buttonPinSelects) {
        const currentValue = select.value;
        for (const option of select.options) {
          if (!option.value) {
            option.hidden = false;
            option.disabled = false;
            continue;
          }
          const blocked = selectedLedPins.has(option.value) && option.value !== currentValue;
          option.hidden = blocked;
          option.disabled = blocked;
        }
        if (select.value && select.selectedOptions.length && select.selectedOptions[0].disabled) {
          select.value = "";
        }
      }

      for (const select of ledPinSelects) {
        const currentValue = select.value;
        for (const option of select.options) {
          if (!option.value) {
            option.hidden = false;
            option.disabled = false;
            continue;
          }
          const blocked = selectedButtonPins.has(option.value) && option.value !== currentValue;
          option.hidden = blocked;
          option.disabled = blocked;
        }
        if (select.value && select.selectedOptions.length && select.selectedOptions[0].disabled) {
          select.value = "";
        }
      }
    }

    for (const row of rows) {
      const pinSelect = row.querySelector("[data-button-pin]");
      const pressSelect = row.querySelector("[data-button-press-type]");
      pinSelect?.addEventListener("change", () => {
        syncPressTypeChoices();
        syncCrossRolePinChoices();
      });
      pressSelect?.addEventListener("change", syncPressTypeChoices);
    }

    if (hardwareButtonsToggle instanceof HTMLInputElement) {
      hardwareButtonsToggle.addEventListener("change", syncHardwareButtonAvailability);
    }

    syncHardwareButtonAvailability();
    syncPressTypeChoices();
    syncCrossRolePinChoices();

    for (const select of ledPinSelects) {
      select.addEventListener("change", syncCrossRolePinChoices);
    }
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

  if (readerRebootDialog instanceof HTMLDialogElement) {
    const countdownNode = readerRebootDialog.querySelector("[data-reader-reboot-countdown]");
    const titleNode = readerRebootDialog.querySelector("[data-reader-reboot-title]");
    const copyNode = readerRebootDialog.querySelector("[data-reader-reboot-copy]");
    const hintNode = readerRebootDialog.querySelector("[data-reader-reboot-hint]");
    const progressBar = readerRebootDialog.querySelector("[data-reader-progress-bar]");
    const progressLabel = readerRebootDialog.querySelector("[data-reader-progress-label]");
    const refreshButton = readerRebootDialog.querySelector("[data-reader-reboot-refresh]");
    const action = readerRebootDialog.dataset.action || "";
    const initialSeconds = Number.parseInt(readerRebootDialog.dataset.seconds || "0", 10);

    function syncRefreshAvailability(ready) {
      if (refreshButton instanceof HTMLButtonElement) {
        refreshButton.disabled = !ready;
      }
    }

    function renderReaderRebootCountdown(seconds) {
      if (countdownNode) {
        countdownNode.textContent = `Neustart in ${Math.max(seconds, 0)}S`;
      }
      if (progressBar instanceof HTMLElement && Number.isFinite(initialSeconds) && initialSeconds > 0) {
        const elapsed = Math.max(0, initialSeconds - Math.max(seconds, 0));
        const percent = (elapsed / initialSeconds) * 100;
        progressBar.style.width = `${Math.max(8, Math.min(percent, 100))}%`;
        progressBar.classList.remove("is-indeterminate");
      }
      if (progressLabel instanceof HTMLElement) {
        progressLabel.textContent = seconds > 0
          ? "Installation abgeschlossen. Das System startet für den Reader neu."
          : "Neustart abgeschlossen.";
      }
    }

    function stripReaderRebootQuery() {
      const currentUrl = new URL(window.location.href);
      currentUrl.searchParams.delete("reader_reboot");
      currentUrl.searchParams.delete("reader_action");
      currentUrl.searchParams.delete("reboot_seconds");
      const normalized = `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`;
      window.history.replaceState({}, "", normalized || "/setup");
    }

    if (titleNode) {
      titleNode.textContent = action === "uninstall" ? "Reader wird deinstalliert" : "Reader wird installiert";
    }
    if (copyNode) {
      copyNode.textContent = action === "uninstall"
        ? "Die Reader-Konfiguration wird entfernt. Das System startet gleich neu."
        : "Die Reader-Konfiguration wird eingerichtet. Das System startet gleich neu.";
    }
    if (hintNode instanceof HTMLElement) {
      hintNode.textContent = "Aktualisiere diese Seite nach einigen Sekunden.";
    }
    syncRefreshAvailability(false);
    if (refreshButton instanceof HTMLButtonElement) {
      refreshButton.addEventListener("click", () => {
        window.location.assign("/setup");
      });
    }

    if (readerRebootDialog.dataset.active === "true" && Number.isFinite(initialSeconds) && initialSeconds > 0) {
      renderReaderRebootCountdown(initialSeconds);
      readerRebootDialog.showModal();
      let remainingSeconds = initialSeconds;
      readerRebootTimer = window.setInterval(() => {
        remainingSeconds -= 1;
        if (remainingSeconds <= 1) {
          stripReaderRebootQuery();
        }
        renderReaderRebootCountdown(remainingSeconds);
        if (remainingSeconds <= 0) {
          window.clearInterval(readerRebootTimer);
          readerRebootTimer = null;
          syncRefreshAvailability(true);
        }
      }, 1000);
    }
  }

  for (const ledRow of document.querySelectorAll(".led-row")) {
    const pinSelect = ledRow.querySelector("[data-led-pin]");
    const brightnessInput = ledRow.querySelector("[data-led-brightness]");
    const testButton = ledRow.querySelector("[data-led-test-button]");
    if (!(pinSelect instanceof HTMLSelectElement) || !(testButton instanceof HTMLButtonElement)) {
      continue;
    }

    function syncLedTestButton() {
      testButton.disabled = !pinSelect.value;
    }

    pinSelect.addEventListener("change", syncLedTestButton);
    syncLedTestButton();

    testButton.addEventListener("click", async () => {
      if (!pinSelect.value) {
        return;
      }
      testButton.disabled = true;
      try {
        await fetch("/api/setup/led-blink", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            pin: pinSelect.value,
            brightness: brightnessInput instanceof HTMLInputElement ? brightnessInput.value : 100,
          }),
        });
      } finally {
        syncLedTestButton();
      }
    });
  }
});
