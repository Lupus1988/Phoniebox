document.addEventListener("DOMContentLoaded", () => {
  const appRoot = document.getElementById("album-editor-app");
  const payloadNode = document.getElementById("album-editor-json");
  const statusNode = document.getElementById("album-editor-status");
  const trackCountPill = document.getElementById("album-track-count-pill");
  const albumNameInput = document.getElementById("album-name-input");
  const albumNameForm = document.getElementById("album-name-form");
  const uploadForm = document.getElementById("album-upload-form");
  const trackInput = document.getElementById("album-track-input");
  const uploadStatusRoot = document.getElementById("album-upload-status");
  const tableBody = document.getElementById("album-track-table-body");
  const selectionSummary = document.getElementById("track-selection-summary");
  const deleteButton = document.getElementById("track-delete-submit");
  const selectAll = document.getElementById("track-select-all");
  const shuffleToggle = document.getElementById("album-shuffle-toggle");
  const processingOverlay = document.getElementById("album-processing-overlay");
  const processingTitle = document.getElementById("album-processing-title");
  const processingSummary = document.getElementById("album-processing-summary");
  const processingBar = document.getElementById("album-processing-progress-bar");
  const processingFileList = document.getElementById("album-processing-file-list");
  const albumId = appRoot?.dataset.albumId || "";
  let state = payloadNode ? JSON.parse(payloadNode.textContent) : {album: {id: albumId, name: "", track_count: 0}, track_rows: []};
  let draggedRow = null;
  let reorderInFlight = false;
  const uploadSubmitButton = uploadForm instanceof HTMLFormElement
    ? uploadForm.querySelector("button[type='submit']")
    : null;

  if (!(appRoot instanceof HTMLElement) || !(tableBody instanceof HTMLElement) || !albumId) {
    return;
  }

  function formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (value >= 1024 * 1024) {
      return `${(value / (1024 * 1024)).toFixed(1)} MB`;
    }
    if (value >= 1024) {
      return `${Math.round(value / 1024)} KB`;
    }
    return `${value} B`;
  }

  function renderUploadTracker(files, progressRatio = 0, completed = false) {
    if (!(uploadStatusRoot instanceof HTMLElement)) {
      return;
    }
    const normalizedFiles = Array.from(files || []);
    if (!normalizedFiles.length) {
      uploadStatusRoot.hidden = true;
      return;
    }

    const title = uploadStatusRoot.querySelector("[data-upload-title]");
    const summary = uploadStatusRoot.querySelector("[data-upload-summary]");
    const bar = uploadStatusRoot.querySelector("[data-upload-progress-bar]");
    const list = uploadStatusRoot.querySelector("[data-upload-file-list]");
    const totalBytes = normalizedFiles.reduce((sum, file) => sum + (file.size || 0), 0);
    const loadedBytes = completed ? totalBytes : Math.max(0, Math.min(totalBytes, totalBytes * progressRatio));

    uploadStatusRoot.hidden = false;
    if (title) {
      title.textContent = completed ? "Upload abgeschlossen" : "Upload läuft";
    }
    if (summary) {
      summary.textContent = `${normalizedFiles.length} Titel · ${formatBytes(loadedBytes)} / ${formatBytes(totalBytes)}`;
    }
    if (bar instanceof HTMLElement) {
      const percent = completed ? 100 : Math.round(progressRatio * 100);
      bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    }
    if (!(list instanceof HTMLElement)) {
      return;
    }

    list.innerHTML = "";
    let consumedBytes = 0;
    for (const file of normalizedFiles) {
      const size = file.size || 0;
      const fileLoaded = completed ? size : Math.max(0, Math.min(size, loadedBytes - consumedBytes));
      const fileRatio = size > 0 ? (fileLoaded / size) : (completed ? 1 : 0);
      const row = document.createElement("div");
      row.className = "upload-file-row";
      row.classList.add(completed || fileRatio >= 1 ? "is-done" : fileRatio > 0 ? "is-active" : "is-pending");

      const meta = document.createElement("div");
      meta.className = "upload-file-meta";

      const name = document.createElement("div");
      name.className = "upload-file-name";
      name.textContent = file.name;

      const detail = document.createElement("div");
      detail.className = "upload-file-detail";
      detail.textContent = formatBytes(size);

      const state = document.createElement("div");
      state.className = "upload-file-state";
      state.textContent = completed || fileRatio >= 1 ? "Fertig" : fileRatio > 0 ? `${Math.round(fileRatio * 100)}%` : "Wartet";

      meta.appendChild(name);
      meta.appendChild(detail);
      row.appendChild(meta);
      row.appendChild(state);
      list.appendChild(row);
      consumedBytes += size;
    }
  }

  function renderUploadError(files, message) {
    if (!(uploadStatusRoot instanceof HTMLElement)) {
      return;
    }
    const normalizedFiles = Array.from(files || []);
    if (!normalizedFiles.length) {
      uploadStatusRoot.hidden = true;
      return;
    }
    renderUploadTracker(normalizedFiles, 0, false);
    const title = uploadStatusRoot.querySelector("[data-upload-title]");
    const summary = uploadStatusRoot.querySelector("[data-upload-summary]");
    const bar = uploadStatusRoot.querySelector("[data-upload-progress-bar]");
    const list = uploadStatusRoot.querySelector("[data-upload-file-list]");
    if (title) {
      title.textContent = "Upload fehlgeschlagen";
    }
    if (summary) {
      summary.textContent = message || "Der Upload konnte nicht abgeschlossen werden.";
    }
    if (bar instanceof HTMLElement) {
      bar.style.width = "0%";
    }
    if (list instanceof HTMLElement) {
      for (const state of list.querySelectorAll(".upload-file-state")) {
        state.textContent = "Fehler";
      }
    }
  }

  function setEditorBusy(busy) {
    for (const element of appRoot.querySelectorAll("button, input")) {
      if (busy) {
        element.setAttribute("disabled", "disabled");
      } else if (
        !(element === uploadSubmitButton && uploadSubmitButton.disabled)
        && !(element === trackInput && trackInput.disabled)
      ) {
        element.removeAttribute("disabled");
      }
    }
  }

  function renderProcessingOverlay(files, progressRatio = 0, completed = false, summaryText = "") {
    if (!(processingOverlay instanceof HTMLElement) || !(processingFileList instanceof HTMLElement)) {
      return;
    }
    const normalizedFiles = Array.from(files || []);
    if (!normalizedFiles.length) {
      processingOverlay.hidden = true;
      return;
    }
    processingOverlay.hidden = false;
    if (processingTitle instanceof HTMLElement) {
      processingTitle.textContent = completed ? "Lautstärke-Anpassung abgeschlossen" : "Lautstärke-Anpassung läuft";
    }
    if (processingSummary instanceof HTMLElement) {
      processingSummary.textContent = summaryText || `${normalizedFiles.length} Titel`;
    }
    if (processingBar instanceof HTMLElement) {
      processingBar.style.width = `${Math.max(0, Math.min(100, Math.round(progressRatio * 100)))}%`;
    }
    processingFileList.innerHTML = "";
    for (const entry of normalizedFiles) {
      const row = document.createElement("div");
      row.className = "upload-file-row";
      const stateName = String(entry.state || "");
      row.classList.add(
        stateName === "normalized" || stateName === "unchanged" ? "is-done" : stateName === "failed" ? "is-pending" : "is-active"
      );
      const meta = document.createElement("div");
      meta.className = "upload-file-meta";
      const name = document.createElement("div");
      name.className = "upload-file-name";
      name.textContent = entry.name || "Titel";
      const detail = document.createElement("div");
      detail.className = "upload-file-detail";
      detail.textContent = entry.detail || "";
      const state = document.createElement("div");
      state.className = "upload-file-state";
      state.textContent =
        stateName === "normalized" || stateName === "unchanged" || stateName === "failed"
          ? (entry.detail || "Fertig")
          : `${Math.max(0, Math.min(100, Math.round(Number(entry.progress_ratio || 0) * 100)))}%`;
      meta.appendChild(name);
      meta.appendChild(detail);
      row.appendChild(meta);
      row.appendChild(state);
      processingFileList.appendChild(row);
    }
  }

  function hideProcessingOverlay() {
    if (processingOverlay instanceof HTMLElement) {
      processingOverlay.hidden = true;
    }
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
    if (shuffleToggle instanceof HTMLInputElement) {
      shuffleToggle.checked = Boolean(state.album?.shuffle_enabled);
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
    const gainButton = row.querySelector("[data-track-gain-button]");
    saveButton?.addEventListener("click", async () => {
      await submitRename(renameForm);
    });
    gainButton?.addEventListener("click", async () => {
      await submitGainEdit(row);
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
            <label class="album-volume-edit-wrap" title="Lautstärke in 0,5 dB-Schritten anpassen">
              <span>Vol.-edit</span>
              <input type="number" class="album-volume-edit-input" data-track-gain-input step="0.5" min="-12" max="12" value="0.0" inputmode="decimal" aria-label="Lautstärkeanpassung in dB">
            </label>
            <button type="button" class="album-icon-button album-track-gain-button" data-track-gain-button aria-label="Lautstärke anpassen" title="Lautstärke anpassen">
              <svg viewBox="0 0 64 64" aria-hidden="true">
                <path d="M14 38h10l12 10V16L24 26H14z" fill="none" stroke="currentColor" stroke-width="4" stroke-linejoin="round"></path>
                <path d="M44 24c3 2 5 5 5 8s-2 6-5 8M50 18c5 4 8 8 8 14s-3 10-8 14" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"></path>
              </svg>
            </button>
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

  async function fetchAlbumPayload() {
    const response = await fetch(`/api/library/album/${encodeURIComponent(albumId)}`, {
      headers: {"X-Requested-With": "XMLHttpRequest"},
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload?.message || "Albumdaten konnten nicht geladen werden.");
    }
    return payload;
  }

  async function postFormDataWithUploadProgress(formData, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/library/album/${encodeURIComponent(albumId)}`);
      xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      xhr.upload.onprogress = (event) => {
        if (typeof onProgress !== "function") {
          return;
        }
        if (event.lengthComputable && event.total > 0) {
          const ratio = Math.max(0, Math.min(1, event.loaded / event.total));
          onProgress(ratio);
          return;
        }
        onProgress(null);
      };
      xhr.onload = () => {
        let payload = {};
        try {
          payload = JSON.parse(xhr.responseText || "{}");
        } catch (_error) {
          payload = {};
        }
        if (xhr.status < 200 || xhr.status >= 300 || payload.ok === false) {
          reject(new Error(payload?.message || "Upload fehlgeschlagen."));
          return;
        }
        resolve(payload);
      };
      xhr.onerror = () => reject(new Error("Upload fehlgeschlagen."));
      xhr.send(formData);
    });
  }

  function selectedUploadFiles() {
    if (!(uploadForm instanceof HTMLFormElement)) {
      return [];
    }
    const inputs = Array.from(uploadForm.querySelectorAll("input[type='file'][name='track_files']"));
    const files = [];
    for (const input of inputs) {
      if (!(input instanceof HTMLInputElement) || !input.files) {
        continue;
      }
      for (const file of Array.from(input.files)) {
        if (file instanceof File && file.name) {
          files.push(file);
        }
      }
    }
    return files;
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

  async function pollAudioProcessingJobs(jobIds) {
    const uniqueJobIds = Array.from(new Set((jobIds || []).filter(Boolean)));
    if (!uniqueJobIds.length) {
      hideProcessingOverlay();
      return;
    }
    const query = new URLSearchParams();
    for (const jobId of uniqueJobIds) {
      query.append("job_id", jobId);
    }
    while (true) {
      const response = await fetch(`/api/library/audio-processing-status?${query.toString()}`, {
        headers: {"X-Requested-With": "XMLHttpRequest"},
      });
      const payload = await response.json();
      const audio = payload?.audio_processing || {};
      const jobs = Array.isArray(audio.jobs) ? audio.jobs : [];
      const files = [];
      for (const job of jobs) {
        for (const file of Array.isArray(job.files) ? job.files : []) {
          files.push(file);
        }
      }
      renderProcessingOverlay(
        files,
        Number(audio.progress_ratio || 0),
        Boolean(audio.complete),
        `${Number(audio.completed_files || 0)} / ${Number(audio.total_files || files.length || 0)} Dateien verarbeitet`
      );
      if (!audio.active) {
        return audio;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    }
  }

  async function submitGainEdit(row) {
    const trackPath = row?.dataset?.trackPath || "";
    const input = row?.querySelector("[data-track-gain-input]");
    if (!(input instanceof HTMLInputElement) || !trackPath) {
      return;
    }
    const gainValue = Number(input.value || 0);
    if (!Number.isFinite(gainValue)) {
      setStatus("Ungültiger dB-Wert.", "error");
      return;
    }
    const rounded = Math.round(gainValue * 2) / 2;
    input.value = rounded.toFixed(1);
    const titleInput = row.querySelector(".album-track-title-input");
    const data = new FormData();
    data.append("action", "volume_edit");
    data.append("track_path", trackPath);
    data.append("gain_db", rounded.toFixed(1));
    setEditorBusy(true);
    renderProcessingOverlay(
      [{name: titleInput instanceof HTMLInputElement ? titleInput.value : trackPath, detail: `${rounded >= 0 ? "+" : ""}${rounded.toFixed(1)} dB`, state: "queued", progress_ratio: 0}],
      0,
      false,
      "Wartet auf Start"
    );
    setStatus("Lautstärke-Anpassung wird gestartet …");
    try {
      const payload = await postFormData(data);
      const jobs = Array.isArray(payload?.audio_processing?.jobs) ? payload.audio_processing.jobs.map((job) => job.job).filter(Boolean) : [];
      await pollAudioProcessingJobs(jobs);
      const refreshed = await fetchAlbumPayload();
      applyPayload(refreshed, `Vol.-edit ${rounded >= 0 ? "+" : ""}${rounded.toFixed(1)} dB angewendet`);
    } catch (error) {
      setStatus(error.message || "Lautstärke-Anpassung fehlgeschlagen.", "error");
    } finally {
      hideProcessingOverlay();
      setEditorBusy(false);
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
    const files = selectedUploadFiles();
    if (!files.length) {
      setStatus("Keine Dateien ausgewählt.", "error");
      return;
    }
    if (uploadSubmitButton instanceof HTMLButtonElement) {
      uploadSubmitButton.disabled = true;
    }
    if (trackInput instanceof HTMLInputElement) {
      trackInput.disabled = true;
    }
    renderUploadTracker(files, 0, false);
    setStatus("Lade Titel hoch …");
    try {
      const data = new FormData();
      data.append("action", "add_tracks");
      for (const file of files) {
        data.append("track_files", file);
      }
      const payload = await postFormDataWithUploadProgress(data, (ratio) => {
        if (typeof ratio === "number") {
          renderUploadTracker(files, ratio, false);
          setStatus(`Lade Titel hoch … ${Math.round(ratio * 100)}%`);
          return;
        }
        renderUploadTracker(files, 0, false);
        setStatus("Lade Titel hoch …");
      });
      if (trackInput instanceof HTMLInputElement) {
        trackInput.value = "";
      }
      renderUploadTracker(files, 1, true);
      applyPayload(payload, "Titel ergänzt");
    } catch (error) {
      renderUploadError(files, error.message || "Upload fehlgeschlagen.");
      setStatus(error.message || "Upload fehlgeschlagen.", "error");
    } finally {
      if (trackInput instanceof HTMLInputElement) {
        trackInput.disabled = false;
      }
      if (uploadSubmitButton instanceof HTMLButtonElement) {
        uploadSubmitButton.disabled = false;
      }
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

  shuffleToggle?.addEventListener("change", async () => {
    const data = new FormData();
    data.append("action", "set_shuffle");
    data.append("shuffle_enabled", shuffleToggle.checked ? "on" : "off");
    setStatus("Speichere Shuffle …");
    shuffleToggle.disabled = true;
    try {
      const payload = await postFormData(data);
      applyPayload(payload, "Shuffle gespeichert");
    } catch (error) {
      shuffleToggle.checked = !shuffleToggle.checked;
      setStatus(error.message || "Shuffle konnte nicht gespeichert werden.", "error");
    } finally {
      shuffleToggle.disabled = false;
    }
  });

  renderRows(state.track_rows || []);
  updateCounters();
  hideProcessingOverlay();
  setStatus("Bereit");
  trackInput?.addEventListener("change", () => {
    const files = selectedUploadFiles();
    renderUploadTracker(files, 0, false);
  });
});
