document.addEventListener("DOMContentLoaded", () => {
  const appRoot = document.getElementById("album-editor-app");
  const payloadNode = document.getElementById("album-editor-json");
  const statusNode = document.getElementById("album-editor-status");
  const trackCountPill = document.getElementById("album-track-count-pill");
  const albumNameInput = document.getElementById("album-name-input");
  const albumNameForm = document.getElementById("album-name-form");
  const uploadForm = document.getElementById("album-upload-form");
  const trackInput = document.getElementById("album-track-input");
  const tableBody = document.getElementById("album-track-table-body");
  const selectionSummary = document.getElementById("track-selection-summary");
  const deleteButton = document.getElementById("track-delete-submit");
  const selectAll = document.getElementById("track-select-all");
  const albumId = appRoot?.dataset.albumId || "";
  let state = payloadNode ? JSON.parse(payloadNode.textContent) : {album: {id: albumId, name: "", track_count: 0}, track_rows: []};
  let draggedRow = null;
  let reorderInFlight = false;

  if (!(appRoot instanceof HTMLElement) || !(tableBody instanceof HTMLElement) || !albumId) {
    return;
  }

  function setStatus(message, kind = "neutral") {
    if (!(statusNode instanceof HTMLElement)) {
      return;
    }
    statusNode.textContent = message || "Bereit";
    statusNode.classList.remove("ok", "neutral", "error");
    statusNode.classList.add(kind === "success" ? "ok" : kind === "error" ? "error" : "neutral");
  }

  function trackRows() {
    return Array.from(tableBody.querySelectorAll(".album-track-row"));
  }

  function checkboxes() {
    return Array.from(tableBody.querySelectorAll("[data-track-checkbox]"));
  }

  function syncSelectionState() {
    const all = checkboxes();
    const selected = all.filter((entry) => entry.checked);
    if (selectionSummary instanceof HTMLElement) {
      selectionSummary.textContent = `Auswahl ${selected.length}/${all.length}`;
    }
    if (deleteButton instanceof HTMLButtonElement) {
      deleteButton.disabled = selected.length === 0;
    }
    if (selectAll instanceof HTMLInputElement) {
      selectAll.checked = all.length > 0 && selected.length === all.length;
      selectAll.indeterminate = selected.length > 0 && selected.length < all.length;
    }
  }

  function updateCounters() {
    if (trackCountPill instanceof HTMLElement) {
      const count = Number(state.album?.track_count || 0);
      trackCountPill.textContent = `${count} ${count === 1 ? "Titel" : "Titel"}`;
    }
    if (albumNameInput instanceof HTMLInputElement) {
      albumNameInput.value = state.album?.name || "";
    }
    document.title = state.album?.name ? `${state.album.name} · Phoniebox Panel` : "Phoniebox Panel";
  }

  function bindRowEvents(row) {
    const dragHandle = row.querySelector(".album-track-drag-handle");
    dragHandle?.addEventListener("dragstart", (event) => {
      draggedRow = row;
      row.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
    });
    dragHandle?.addEventListener("dragend", async () => {
      row.classList.remove("is-dragging");
      const changed = draggedRow === row;
      draggedRow = null;
      syncOrderIndexes();
      if (changed) {
        await saveOrder();
      }
    });
    row.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (!draggedRow || draggedRow === row) {
        return;
      }
      const bounds = row.getBoundingClientRect();
      const before = event.clientY < bounds.top + bounds.height / 2;
      if (before) {
        tableBody.insertBefore(draggedRow, row);
      } else {
        tableBody.insertBefore(draggedRow, row.nextElementSibling);
      }
    });

    const checkbox = row.querySelector("[data-track-checkbox]");
    checkbox?.addEventListener("change", syncSelectionState);

    const renameForm = row.querySelector("[data-track-rename-form]");
    const saveButton = row.querySelector("[data-track-save-button]");
    const deleteSingleButton = row.querySelector("[data-track-delete-button]");
    saveButton?.addEventListener("click", async () => {
      await submitRename(renameForm);
    });
    deleteSingleButton?.addEventListener("click", async () => {
      const trackPath = row.dataset.trackPath || "";
      if (!trackPath) {
        return;
      }
      await deleteTracks([trackPath], "Titel wird gelöscht …", "Titel gelöscht");
    });
    renameForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      await submitRename(renameForm);
    });
  }

  function renderRows(rows) {
    tableBody.innerHTML = "";
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.className = "album-track-row";
      tr.dataset.trackPath = row.path;
      tr.innerHTML = `
        <td class="album-track-select-col">
          <input type="checkbox" value="${row.path}" data-track-checkbox>
        </td>
        <td class="album-track-order-col" data-track-index>${row.index}</td>
        <td class="album-track-drag-col">
          <button type="button" class="album-track-drag-handle" aria-label="Titel verschieben" draggable="true">
            <svg viewBox="0 0 64 64" aria-hidden="true">
              <path d="M32 14v36" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"></path>
              <path d="M24 22l8-8 8 8" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
              <path d="M24 42l8 8 8-8" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
            </svg>
          </button>
        </td>
        <td class="album-track-title-col">
          <form method="post" class="album-track-rename-form" data-track-rename-form>
            <input type="hidden" name="action" value="rename_track">
            <input type="hidden" name="track_path" value="${row.path}">
            <input type="text" name="new_name" value="${row.display_name}" class="album-track-title-input" required>
          </form>
        </td>
        <td class="album-track-actions-cell">
          <div class="album-track-actions-wrap">
            <button type="button" class="album-icon-button album-track-save-button" data-track-save-button aria-label="Titel speichern" title="Titel speichern">
              <svg viewBox="0 0 64 64" aria-hidden="true">
                <path d="M14 12h30l6 6v34H14z" fill="none" stroke="currentColor" stroke-width="4" stroke-linejoin="round"></path>
                <path d="M22 12v14h20V12M22 46h20M24 36h16" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
              </svg>
            </button>
            <button type="button" class="album-icon-button danger album-track-delete-button" data-track-delete-button aria-label="Titel löschen" title="Titel löschen">
              <svg viewBox="0 0 64 64" aria-hidden="true">
                <path d="M20 20h24l-2 30H22L20 20Z" fill="none" stroke="currentColor" stroke-width="4" stroke-linejoin="round"></path>
                <path d="M16 20h32M26 20v-4h12v4M28 28v14M36 28v14" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"></path>
              </svg>
            </button>
          </div>
        </td>
      `;
      tableBody.appendChild(tr);
      bindRowEvents(tr);
    }
    syncOrderIndexes();
    syncSelectionState();
  }

  function applyPayload(payload, message) {
    if (!payload || payload.ok === false) {
      return;
    }
    state = payload;
    updateCounters();
    renderRows(payload.track_rows || []);
    setStatus(message || payload.message || "Gespeichert", "success");
  }

  function syncOrderIndexes() {
    trackRows().forEach((row, index) => {
      const indexCell = row.querySelector("[data-track-index]");
      if (indexCell) {
        indexCell.textContent = String(index + 1);
      }
    });
  }

  async function postFormData(formData) {
    const response = await fetch(`/library/album/${encodeURIComponent(albumId)}`, {
      method: "POST",
      headers: {"X-Requested-With": "XMLHttpRequest"},
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload?.message || "Speichern fehlgeschlagen.");
    }
    return payload;
  }

  async function submitRename(form) {
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    const data = new FormData(form);
    setStatus("Speichere Titel …");
    try {
      const payload = await postFormData(data);
      applyPayload(payload, "Titel gespeichert");
    } catch (error) {
      setStatus(error.message || "Titel konnte nicht gespeichert werden.", "error");
    }
  }

  async function saveOrder() {
    if (reorderInFlight) {
      return;
    }
    reorderInFlight = true;
    const data = new FormData();
    data.append("action", "reorder_tracks");
    for (const row of trackRows()) {
      data.append("track_order", row.dataset.trackPath || "");
    }
    setStatus("Reihenfolge wird gespeichert …");
    try {
      const payload = await postFormData(data);
      applyPayload(payload, "Reihenfolge gespeichert");
    } catch (error) {
      setStatus(error.message || "Reihenfolge konnte nicht gespeichert werden.", "error");
    } finally {
      reorderInFlight = false;
    }
  }

  async function deleteTracks(selected, pendingMessage, doneMessage) {
    if (!selected.length) {
      syncSelectionState();
      return;
    }
    const data = new FormData();
    data.append("action", "remove_tracks");
    for (const entry of selected) {
      data.append("track_path", entry);
    }
    setStatus(pendingMessage || "Lösche Titel …");
    try {
      const payload = await postFormData(data);
      applyPayload(payload, doneMessage || "Titel entfernt");
    } catch (error) {
      setStatus(error.message || "Titel konnten nicht gelöscht werden.", "error");
    }
  }

  async function deleteSelectedTracks() {
    const selected = checkboxes().filter((entry) => entry.checked).map((entry) => entry.value || "");
    await deleteTracks(selected, "Lösche Auswahl …", "Auswahl gelöscht");
  }

  albumNameForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(albumNameForm);
    setStatus("Speichere Albumname …");
    try {
      const payload = await postFormData(data);
      applyPayload(payload, "Albumname gespeichert");
    } catch (error) {
      setStatus(error.message || "Albumname konnte nicht gespeichert werden.", "error");
    }
  });

  uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!(trackInput instanceof HTMLInputElement) || !trackInput.files?.length) {
      setStatus("Keine Dateien ausgewählt.", "error");
      return;
    }
    setStatus("Lade Titel hoch …");
    try {
      const payload = await postFormData(new FormData(uploadForm));
      if (trackInput) {
        trackInput.value = "";
      }
      applyPayload(payload, "Titel ergänzt");
    } catch (error) {
      setStatus(error.message || "Upload fehlgeschlagen.", "error");
    }
  });

  deleteButton?.addEventListener("click", async () => {
    await deleteSelectedTracks();
  });

  selectAll?.addEventListener("change", () => {
    const checked = Boolean(selectAll.checked);
    for (const checkbox of checkboxes()) {
      checkbox.checked = checked;
    }
    syncSelectionState();
  });

  renderRows(state.track_rows || []);
  updateCounters();
  setStatus("Bereit");
});
