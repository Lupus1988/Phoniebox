document.addEventListener("DOMContentLoaded", () => {
  const forms = document.querySelectorAll("[data-player-form]");
  if (!forms.length) {
    return;
  }
  const seekSlider = document.getElementById("player-seek-slider");
  const seekBubble = document.getElementById("player-seek-bubble");
  let pollTimer = null;

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

  function applySnapshot(payload) {
    const player = payload.player_state || {};
    const runtime = payload.runtime_state || {};
    const sleepLevel = payload.sleep_level ?? runtime.sleep_timer?.level ?? 0;
    const isPlaying = Boolean(player.is_playing);

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
    const formData = new FormData(form);
    if (submitter?.name) {
      formData.set(submitter.name, submitter.value);
    }
    const payload = Object.fromEntries(formData.entries());

    const response = await fetch("/api/player/action", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      return;
    }
    applySnapshot(await response.json());
  }

  async function pollSnapshot() {
    try {
      const response = await fetch("/api/player/snapshot");
      if (!response.ok) {
        return;
      }
      applySnapshot(await response.json());
    } finally {
      pollTimer = window.setTimeout(pollSnapshot, 1000);
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
      const response = await fetch("/api/player/action", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        return;
      }
      applySnapshot(await response.json());
      hideBubble();
    });

    updateSeekVisuals(Number(seekSlider.value || 0), Number(seekSlider.max || 0));
  }

  pollTimer = window.setTimeout(pollSnapshot, 1000);
});
