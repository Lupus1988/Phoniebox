document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("settings-form");
  if (!form) {
    return;
  }

  let saveTimer = null;
  let inFlight = false;
  let pending = false;

  function collectPayload() {
    const formData = new FormData(form);
    return Object.fromEntries(formData.entries());
  }

  async function saveSettings() {
    if (inFlight) {
      pending = true;
      return;
    }

    inFlight = true;
    pending = false;
    const payload = collectPayload();

    for (const field of form.elements) {
      if (field instanceof HTMLElement) {
        field.disabled = true;
      }
    }

    try {
      await fetch("/api/settings", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
    } finally {
      for (const field of form.elements) {
        if (field instanceof HTMLElement) {
          field.disabled = false;
        }
      }
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

  form.addEventListener("change", scheduleSave);
});
