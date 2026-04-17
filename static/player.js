document.addEventListener("DOMContentLoaded", () => {
  const forms = document.querySelectorAll("[data-player-form]");
  if (!forms.length) {
    return;
  }
  const seekSlider = document.getElementById("player-seek-slider");
  const seekBubble = document.getElementById("player-seek-bubble");
  const statusNode = document.getElementById("player-action-status");
  let pollTimer = null;
  let actionInFlight = false;
  let visiblePollMs = 1000;
  let hiddenPollMs = 3000;

  function nextPollDelay() {
    return document.hidden ? hiddenPollMs : visiblePollMs;
  }

  function formatMmss(totalSeconds) {
    const safe = Math.max(0, Number(totalSeconds) || 0);
    const minutes = Math.floor(safe / 60);
    const seconds = safe % 60;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  function syncSeekControls(value, duration) {
    const safeValue = `${Math.max(0, Number(value) || 0)}`;
    const safeDuration = `${Math.max(0, Number(duration) || 0)}`;
    if (seekSlider) {
      seekSlider.value = safeValue;
      seekSlider.max = safeDuration;
    }
  }

  function updateSeekBubble(position, duration) {
    if (!seekSlider || !seekBubble) {
      return;
    }
    const safeDuration = Math.max(0, Number(duration) || 0);
    const safePosition = Math.max(0, Number(position) || 0);
    const percent = safeDuration > 0 ? safePosition / safeDuration : 0;
    seekBubble.textContent = formatMmss(safePosition);
    seekBubble.style.left = `calc(${percent * 100}% - 1px)`;
  }

  function updateSeekVisuals(position, duration) {
    if (!seekSlider) {
      return 0;
    }
    const safeDuration = Math.max(0, Number(duration) || 0);
    const safePosition = Math.max(0, Number(position) || 0);
    const percent = safeDuration > 0 ? (safePosition / safeDuration) * 100 : 0;
    seekSlider.style.setProperty("--timeline-progress", `${percent}%`);
    const coverShell = document.getElementById("player-cover-shell");
    if (coverShell) {
      coverShell.style.setProperty("--cover-progress", `${percent}%`);
    }
    return percent;
  }

  function updateQueue(items) {
    const queue = document.getElementById("player-queue");
    if (!queue) {
      return;
    }
    queue.innerHTML = "";
    const entries = items && items.length ? items : ["Keine weiteren Titel"];
    for (const item of entries) {
      const li = document.createElement("li");
      li.textContent = item;
      queue.appendChild(li);
    }
  }

  function updateCover(player) {
    const stage = document.querySelector(".cover-stage");
    if (!(stage instanceof HTMLElement)) {
      return;
    }
    const coverUrl = String(player.cover_url || "").trim();
    const albumName = String(player.current_album || "").trim();
    const initial = albumName ? albumName.slice(0, 1).toUpperCase() : "P";
    const existingImage = document.getElementById("player-cover-image");
    const existingPlaceholder = document.getElementById("player-cover-placeholder");

    if (coverUrl) {
      let image = existingImage;
      if (!(image instanceof HTMLImageElement)) {
        image = document.createElement("img");
        image.id = "player-cover-image";
        stage.innerHTML = "";
        stage.appendChild(image);
      }
      image.src = coverUrl;
      image.alt = albumName ? `Cover von ${albumName}` : "Albumcover";
      return;
    }

    let placeholder = existingPlaceholder;
    if (!(placeholder instanceof HTMLElement)) {
      placeholder = document.createElement("div");
      placeholder.id = "player-cover-placeholder";
      placeholder.className = "cover-art-placeholder";
      stage.innerHTML = "";
      stage.appendChild(placeholder);
    }
    placeholder.innerHTML = `<span>${initial}</span>`;
  }

  function setStatus(message, tone = "neutral") {
    if (!statusNode) {
      return;
    }
    statusNode.textContent = message || "";
    statusNode.dataset.tone = tone;
  }

  function actionLabel(action) {
    const labels = {
      toggle_play: "Wiedergabe wird aktualisiert …",
      prev: "Vorheriger Titel …",
      next: "Nächster Titel …",
      stop: "Wiedergabe wird gestoppt …",
      volume_down: "Lautstärke wird gesenkt …",
      volume_up: "Lautstärke wird erhöht …",
      mute: "Stummschaltung wird geändert …",
      sleep_reset: "Sleeptimer wird zurückgesetzt …",
      sleep_down: "Sleeptimer wird reduziert …",
      sleep_up: "Sleeptimer wird erhöht …",
      clear_queue: "Warteschlange wird geleert …",
      seek: "Position wird gesetzt …",
    };
    return labels[action] || "Player wird aktualisiert …";
  }

  function extractError(payload, fallback) {
    return payload?.error || payload?.message || fallback;
  }

  function setFormsDisabled(disabled) {
    for (const form of forms) {
      for (const field of form.elements) {
        if (field instanceof HTMLElement) {
          field.toggleAttribute("disabled", disabled);
        }
      }
    }
    if (seekSlider) {
      seekSlider.toggleAttribute("disabled", disabled);
    }
  }

  function applySnapshot(payload) {
    const player = payload.player_state || {};
    const runtime = payload.runtime_state || {};
    const sleepLevel = payload.sleep_level ?? runtime.sleep_timer?.level ?? 0;
    const isPlaying = Boolean(player.is_playing);
    visiblePollMs = Math.max(250, Number(payload.player_poll_visible_ms) || visiblePollMs);
    hiddenPollMs = Math.max(750, Number(payload.player_poll_hidden_ms) || hiddenPollMs);

    const setText = (id, value) => {
      const el = document.getElementById(id);
      if (el) {
        el.textContent = value;
      }
    };

    const setHtml = (id, value) => {
      const el = document.getElementById(id);
      if (el) {
        el.innerHTML = value;
      }
    };

    setText("player-album", player.current_album || "");
    setText("player-album-secondary", player.current_album || "");
    setText("player-track", player.current_track || "");
    updateCover(player);
    setText("player-volume-value", `${payload.volume_percent}%`);
    const volumeValue = document.getElementById("player-volume-value");
    if (volumeValue) {
      volumeValue.classList.toggle("muted", Boolean(payload.volume_muted));
    }
    setHtml("player-sleep-value", `Stufe ${sleepLevel} &middot; ${payload.sleep_remaining_label || "00:00"}`);
    setText("player-position-label", payload.position_label || "00:00");
    setText("player-duration-label", payload.duration_label || "00:00");
    setText("player-toggle-symbol", isPlaying ? "⏸" : "▶");
    const toggleButton = document.getElementById("player-toggle-button");
    if (toggleButton) {
      const label = isPlaying ? "Pause" : "Wiedergabe";
      toggleButton.setAttribute("aria-label", label);
      toggleButton.setAttribute("title", label);
    }

    syncSeekControls(player.position_seconds || 0, player.duration_seconds || 0);
    updateSeekVisuals(player.position_seconds || 0, player.duration_seconds || 0);
    updateSeekBubble(player.position_seconds || 0, player.duration_seconds || 0);

    updateQueue(player.queue || []);
  }

  async function submitPlayerForm(form, submitter) {
    if (actionInFlight) {
      return;
    }
    const formData = new FormData(form);
    if (submitter?.name) {
      formData.set(submitter.name, submitter.value);
    }
    const payload = Object.fromEntries(formData.entries());

    actionInFlight = true;
    setFormsDisabled(true);
    setStatus(actionLabel(payload.action), "busy");

    try {
      const response = await fetch("/api/player/action", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok === false) {
        setStatus(extractError(result, "Aktion konnte nicht ausgeführt werden."), "error");
        return;
      }
      applySnapshot(result);
      setStatus(result.message || "Playerstatus aktualisiert.", "success");
    } catch (_error) {
      setStatus("Playeraktion fehlgeschlagen.", "error");
    } finally {
      actionInFlight = false;
      setFormsDisabled(false);
    }
  }

  async function pollSnapshot() {
    try {
      const response = await fetch("/api/player/snapshot");
      if (!response.ok) {
        return;
      }
      applySnapshot(await response.json());
    } finally {
      pollTimer = window.setTimeout(pollSnapshot, nextPollDelay());
    }
  }

  for (const form of forms) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await submitPlayerForm(form, event.submitter);
    });
  }

  if (seekSlider) {
    const showBubble = () => seekBubble?.classList.add("visible");
    const hideBubble = () => seekBubble?.classList.remove("visible");

    seekSlider.addEventListener("input", () => {
      const duration = Number(seekSlider.max || 0);
      const position = Number(seekSlider.value || 0);
      syncSeekControls(position, duration);
      updateSeekVisuals(position, duration);
      updateSeekBubble(position, duration);
      const positionLabel = document.getElementById("player-position-label");
      if (positionLabel) {
        positionLabel.textContent = formatMmss(position);
      }
    });

    seekSlider.addEventListener("pointerdown", showBubble);
    seekSlider.addEventListener("pointerup", hideBubble);
    seekSlider.addEventListener("focus", showBubble);
    seekSlider.addEventListener("blur", hideBubble);
    seekSlider.addEventListener("mouseenter", showBubble);
    seekSlider.addEventListener("mouseleave", hideBubble);

    seekSlider.addEventListener("change", async () => {
      const payload = {
        action: "seek",
        seek_position: Number(seekSlider.value || 0),
      };
      setStatus(actionLabel(payload.action), "busy");
      const response = await fetch("/api/player/action", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok === false) {
        setStatus(extractError(result, "Position konnte nicht gesetzt werden."), "error");
        return;
      }
      applySnapshot(result);
      setStatus(result.message || "Position aktualisiert.", "success");
      hideBubble();
    });

    updateSeekVisuals(Number(seekSlider.value || 0), Number(seekSlider.max || 0));
  }

  setStatus("Bereit.");
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !actionInFlight) {
      if (pollTimer) {
        window.clearTimeout(pollTimer);
      }
      pollTimer = window.setTimeout(pollSnapshot, 150);
    }
  });
  pollTimer = window.setTimeout(pollSnapshot, nextPollDelay());
});
