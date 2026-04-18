document.addEventListener("DOMContentLoaded", () => {
  const albumsPayload = document.getElementById("library-albums-json");
  const albums = albumsPayload ? JSON.parse(albumsPayload.textContent) : [];

  const createModal = document.getElementById("album-create-modal");
  const createModalBody = document.getElementById("album-create-modal-body");
  const createOpenButton = document.getElementById("open-album-create");
  const createNameInput = document.getElementById("album-create-name");
  const createWarning = document.getElementById("album-create-warning");
  const createForm = document.getElementById("album-create-form");
  const createTrackInput = document.getElementById("album-track-input-create");
  const createTrackTrigger = document.getElementById("album-track-trigger-create");
  const createUploadStatus = document.getElementById("album-create-upload-status");
  const createAudioStatus = document.getElementById("album-create-audio-status");
  const createSubmitButton = document.getElementById("album-create-submit");

  const editModal = document.getElementById("album-edit-modal");
  const editTitle = document.getElementById("album-edit-title");
  const editCurrentName = document.getElementById("album-edit-current-name");
  const editHome = document.getElementById("album-edit-home");
  const editRename = document.getElementById("album-edit-rename");
  const editRemove = document.getElementById("album-edit-remove");
  const editAdd = document.getElementById("album-edit-add");
  const trackList = document.getElementById("album-track-list");
  const removeSelectedButton = document.getElementById("album-remove-selected");
  const trackSelectionStatus = document.getElementById("album-track-selection-status");
  const addTracksForm = document.getElementById("album-add-tracks-form");
  const addTracksAlbumId = document.getElementById("album-add-id");
  const trackInput = document.getElementById("album-track-input");
  const trackTrigger = document.getElementById("album-track-trigger");
  const addUploadStatus = document.getElementById("album-add-upload-status");
  const addSubmitButton = document.getElementById("album-add-submit");
  const renameAlbumId = document.getElementById("album-rename-id");
  const renameFolder = document.getElementById("album-rename-folder");
  const renamePlaylist = document.getElementById("album-rename-playlist");
  const renameTrackCount = document.getElementById("album-rename-track-count");
  const renameRfid = document.getElementById("album-rename-rfid");
  const renameCover = document.getElementById("album-rename-cover");
  const renameNameInput = document.getElementById("album-rename-name");
  const renameWarning = document.getElementById("album-rename-warning");

  const linkModal = document.getElementById("rfid-link-modal");
  const albumText = document.getElementById("rfid-link-album");
  const messageText = document.getElementById("rfid-link-message");
  const confirmButton = document.getElementById("rfid-link-confirm");
  const cancelButton = document.getElementById("rfid-link-cancel");
  const linkInputWrap = document.getElementById("rfid-link-input-wrap");
  const linkInput = document.getElementById("rfid-link-input");
  const unlinkInfoWrap = document.getElementById("rfid-unlink-info-wrap");
  const unlinkValue = document.getElementById("rfid-unlink-value");
  const confirmView = document.getElementById("rfid-link-confirm-view");
  const unlinkFinalView = document.getElementById("rfid-unlink-final-view");
  const unlinkFinalConfirm = document.getElementById("rfid-unlink-final-confirm");
  const unlinkFinalCancel = document.getElementById("rfid-unlink-final-cancel");
  const unlinkAlbumId = document.getElementById("rfid-unlink-album-id");
  const unlinkForm = document.getElementById("rfid-unlink-form");
  const deleteModal = document.getElementById("album-delete-modal");
  const deleteAlbumName = document.getElementById("album-delete-name");
  const deleteConfirm = document.getElementById("album-delete-confirm");
  const deleteCancel = document.getElementById("album-delete-cancel");
  const deleteAlbumId = document.getElementById("album-delete-album-id");
  const deleteForm = document.getElementById("album-delete-form");
  const coverForm = document.getElementById("album-cover-form");
  const coverAlbumId = document.getElementById("album-cover-album-id");
  const coverInput = document.getElementById("album-cover-input");

  let activeAlbum = null;
  let pendingAction = null;
  let pollTimer = null;
  let pendingDeleteAlbum = null;

  function stopPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function findAlbum(albumId) {
    return albums.find((entry) => entry.id === albumId) || null;
  }

  function restoreConfirmView() {
    if (!activeAlbum) {
      return;
    }
    const unlinkMode = pendingAction === "unlink";
    albumText.textContent = `Album: ${activeAlbum.name}`;
    messageText.textContent = unlinkMode ? "link entfernen?" : "link hinzufügen?";
    confirmButton.hidden = false;
    confirmButton.textContent = "Ja";
    confirmButton.classList.remove("danger");
    confirmButton.classList.add("primary");
    cancelButton.textContent = "Nein";
    if (linkInputWrap) {
      linkInputWrap.hidden = unlinkMode;
    }
    if (unlinkInfoWrap) {
      unlinkInfoWrap.hidden = !unlinkMode;
    }
    if (linkInput) {
      if (unlinkMode) {
        linkInput.value = "";
      } else if (!linkInput.value) {
        linkInput.value = activeAlbum.rfid_uid || "";
      }
    }
    if (unlinkValue) {
      unlinkValue.textContent = activeAlbum.rfid_uid || "-";
    }
    confirmView.classList.remove("link-warning-surface");
    syncConfirmState();
    showLinkView("confirm");
  }

  function showEditSection(section) {
    editHome.hidden = section !== "home";
    editRename.hidden = section !== "rename";
    editRemove.hidden = section !== "remove";
    editAdd.hidden = section !== "add";
  }

  function openCreateModal() {
    if (!createModal) {
      return;
    }
    if (createWarning) {
      createWarning.hidden = true;
    }
    createModalBody?.classList.remove("create-warning-surface");
    hideAudioTracker(createAudioStatus);
    createModal.showModal();
    window.setTimeout(() => createNameInput?.focus(), 60);
  }

  function closeCreateModal() {
    createModal?.close();
  }

  function hideAudioTracker(root) {
    if (root instanceof HTMLElement) {
      root.hidden = true;
    }
  }

  function createNameExists(name) {
    const normalized = (name || "").trim().toLowerCase();
    return Boolean(normalized) && albums.some((entry) => (entry.name || "").trim().toLowerCase() === normalized);
  }

  function renameNameExists(name, albumId) {
    const normalized = (name || "").trim().toLowerCase();
    return Boolean(normalized) && albums.some((entry) => entry.id !== albumId && (entry.name || "").trim().toLowerCase() === normalized);
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

  function renderUploadTracker(root, files, progressRatio = 0, completed = false) {
    if (!(root instanceof HTMLElement)) {
      return;
    }
    const normalizedFiles = Array.from(files || []);
    if (!normalizedFiles.length) {
      root.hidden = true;
      return;
    }

    const title = root.querySelector("[data-upload-title]");
    const summary = root.querySelector("[data-upload-summary]");
    const bar = root.querySelector("[data-upload-progress-bar]");
    const list = root.querySelector("[data-upload-file-list]");
    const totalBytes = normalizedFiles.reduce((sum, file) => sum + (file.size || 0), 0);
    const loadedBytes = completed ? totalBytes : Math.max(0, Math.min(totalBytes, totalBytes * progressRatio));

    root.hidden = false;
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
      name.textContent = file.webkitRelativePath || file.name;

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

  function renderUploadError(root, files, message) {
    if (!(root instanceof HTMLElement)) {
      return;
    }
    const normalizedFiles = Array.from(files || []);
    if (!normalizedFiles.length) {
      root.hidden = true;
      return;
    }

    renderUploadTracker(root, normalizedFiles, 0, false);
    const title = root.querySelector("[data-upload-title]");
    const summary = root.querySelector("[data-upload-summary]");
    const bar = root.querySelector("[data-upload-progress-bar]");
    const list = root.querySelector("[data-upload-file-list]");

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

  function renderUploadFallback(root, files, message) {
    renderUploadTracker(root, files, 1, true);
    if (!(root instanceof HTMLElement)) {
      return;
    }
    const title = root.querySelector("[data-upload-title]");
    const summary = root.querySelector("[data-upload-summary]");
    if (title) {
      title.textContent = "Standard-Upload wird gestartet";
    }
    if (summary) {
      summary.textContent = message || "Der Browser-Upload war instabil. Standard-Upload läuft weiter.";
    }
  }

  function renderAudioProcessingTracker(root, entries, progressRatio = 0, completed = false, titleText = "", summaryText = "") {
    if (!(root instanceof HTMLElement)) {
      return;
    }
    const normalizedEntries = Array.from(entries || []);
    if (!normalizedEntries.length) {
      root.hidden = true;
      return;
    }

    const title = root.querySelector("[data-audio-title]");
    const summary = root.querySelector("[data-audio-summary]");
    const bar = root.querySelector("[data-audio-progress-bar]");
    const list = root.querySelector("[data-audio-file-list]");

    root.hidden = false;
    if (title) {
      title.textContent = titleText || (completed ? "Audio-Verarbeitung abgeschlossen" : "Audio wird verarbeitet");
    }
    if (summary) {
      summary.textContent = summaryText || `${normalizedEntries.length} Titel`;
    }
    if (bar instanceof HTMLElement) {
      bar.style.width = `${Math.max(0, Math.min(100, Math.round(progressRatio * 100)))}%`;
    }
    if (!(list instanceof HTMLElement)) {
      return;
    }

    list.innerHTML = "";
    for (const entry of normalizedEntries) {
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
      name.textContent = entry.name || entry.path || "Datei";

      const detail = document.createElement("div");
      detail.className = "upload-file-detail";
      detail.textContent = entry.detail || "";

      const state = document.createElement("div");
      state.className = "upload-file-state";
      if (stateName === "normalized" || stateName === "unchanged" || stateName === "failed") {
        state.textContent = entry.detail || "Fertig";
      } else {
        state.textContent = `${Math.max(0, Math.min(100, Math.round(Number(entry.progress_ratio || 0) * 100)))}%`;
      }

      meta.appendChild(name);
      meta.appendChild(detail);
      row.appendChild(meta);
      row.appendChild(state);
      list.appendChild(row);
    }
  }

  async function pollAudioProcessingJobs(jobIds, statusRoot) {
    const uniqueJobIds = Array.from(new Set((jobIds || []).filter(Boolean)));
    if (!uniqueJobIds.length) {
      hideAudioTracker(statusRoot);
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
      const payload = await parseJsonResponse(response);
      const audio = payload?.audio_processing || {};
      const jobs = Array.isArray(audio.jobs) ? audio.jobs : [];
      const files = [];
      for (const job of jobs) {
        for (const file of Array.isArray(job.files) ? job.files : []) {
          files.push(file);
        }
      }
      renderAudioProcessingTracker(
        statusRoot,
        files,
        Number(audio.progress_ratio || 0),
        Boolean(audio.complete),
        Boolean(audio.complete) ? "Audio-Verarbeitung abgeschlossen" : "Audio wird verarbeitet",
        `${Number(audio.completed_files || 0)} / ${Number(audio.total_files || files.length || 0)} Dateien verarbeitet`
      );
      if (!audio.active) {
        return audio;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    }
  }

  function extractUploadErrorMessage(request) {
    const fallback = request.status >= 400
      ? `Der Upload wurde vom Server abgelehnt (${request.status}).`
      : "Der Upload konnte nicht abgeschlossen werden.";
    const raw = String(request.responseText || "").trim();
    if (!raw) {
      return fallback;
    }
    try {
      const payload = JSON.parse(raw);
      if (payload && typeof payload.message === "string" && payload.message.trim()) {
        return payload.message.trim();
      }
    } catch (_error) {
      // Ignore and try a coarse HTML/text extraction below.
    }
    const condensed = raw.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    if (condensed) {
      return condensed.slice(0, 220);
    }
    return fallback;
  }

  async function parseJsonResponse(response) {
    const raw = await response.text();
    if (!raw) {
      return {};
    }
    try {
      return JSON.parse(raw);
    } catch (_error) {
      return {ok: false, message: raw.slice(0, 220)};
    }
  }

  function uploadSingleTrack(uploadUrl, albumId, file, files, statusRoot, bytesDone, totalBytes, allowFallback = true) {
    return new Promise((resolve, reject) => {
      const formData = new FormData();
      formData.append("action", "add_tracks");
      formData.append("album_id", albumId);
      formData.append("track_files", file, file.name || "track");

      const request = new XMLHttpRequest();
      request.open("POST", uploadUrl);
      request.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      request.upload.addEventListener("progress", (progressEvent) => {
        if (!progressEvent.lengthComputable || totalBytes <= 0) {
          return;
        }
        const ratio = Math.max(0, Math.min(1, (bytesDone + progressEvent.loaded) / totalBytes));
        renderUploadTracker(statusRoot, files, ratio, false);
      });
      request.addEventListener("load", () => {
        if (request.status === 404 && allowFallback && uploadUrl !== "/library") {
          uploadSingleTrack("/library", albumId, file, files, statusRoot, bytesDone, totalBytes, false)
            .then(resolve)
            .catch(reject);
          return;
        }
        if (request.status >= 200 && request.status < 300) {
          let payload = null;
          try {
            payload = JSON.parse(request.responseText || "{}");
          } catch (_error) {
            payload = null;
          }
          if (!payload || payload.ok !== false) {
            resolve(payload || {});
            return;
          }
        }
        reject(new Error(extractUploadErrorMessage(request)));
      });
      request.addEventListener("error", () => {
        reject(new Error("Upload-Verbindung abgebrochen. Bitte erneut versuchen."));
      });
      request.send(formData);
    });
  }

  function bindCreateAlbumUpload(form, fileInput, statusRoot, submitButton, validate) {
    if (!(form instanceof HTMLFormElement) || !(fileInput instanceof HTMLInputElement)) {
      return;
    }

    form.addEventListener("submit", async (event) => {
      if (typeof validate === "function" && !validate()) {
        event.preventDefault();
        return;
      }

      const files = Array.from(fileInput.files || []);
      if (!files.length) {
        // Leeres Album weiterhin als normaler Form-Submit.
        return;
      }

      event.preventDefault();
      submitButton?.setAttribute("disabled", "disabled");
      renderUploadTracker(statusRoot, files, 0, false);
      hideAudioTracker(createAudioStatus);

      const createPayload = new FormData();
      createPayload.append("action", "import_album");
      createPayload.append("name", String(createNameInput?.value || "").trim());
      const postUrl = form.getAttribute("action") || window.location.pathname || "/library";

      try {
        let createResponse = await fetch(postUrl, {
          method: form.method || "POST",
          headers: {"X-Requested-With": "XMLHttpRequest"},
          body: createPayload,
        });
        if (createResponse.status === 404 && postUrl !== "/library") {
          createResponse = await fetch("/library", {
            method: form.method || "POST",
            headers: {"X-Requested-With": "XMLHttpRequest"},
            body: createPayload,
          });
        }
        const createJson = await parseJsonResponse(createResponse);
        if (!createResponse.ok || createJson.ok === false) {
          throw new Error(createJson?.message || "Album konnte nicht angelegt werden.");
        }

        const albumId = String(createJson?.album?.id || "").trim();
        if (!albumId) {
          throw new Error("Album-ID fehlt in der Serverantwort.");
        }

        const totalBytes = files.reduce((sum, item) => sum + (item.size || 0), 0);
        let bytesDone = 0;
        const scheduledJobs = [];
        for (const file of files) {
          const uploadPayload = await uploadSingleTrack(postUrl, albumId, file, files, statusRoot, bytesDone, totalBytes);
          const audioProcessing = uploadPayload?.audio_processing || {};
          for (const job of Array.isArray(audioProcessing.jobs) ? audioProcessing.jobs : []) {
            if (job?.job) {
              scheduledJobs.push(job.job);
            }
          }
          bytesDone += file.size || 0;
          const ratio = totalBytes > 0 ? Math.min(1, bytesDone / totalBytes) : 1;
          renderUploadTracker(statusRoot, files, ratio, false);
        }

        renderUploadTracker(statusRoot, files, 1, true);
        await pollAudioProcessingJobs(scheduledJobs, createAudioStatus);
        closeCreateModal();
        window.setTimeout(() => window.location.assign("/library"), 120);
      } catch (error) {
        submitButton?.removeAttribute("disabled");
        renderUploadError(statusRoot, files, error instanceof Error ? error.message : "Upload fehlgeschlagen.");
        hideAudioTracker(createAudioStatus);
      }
    });
  }

  function bindUploadProgress(form, fileInput, statusRoot, submitButton, validate, options = {}) {
    if (!(form instanceof HTMLFormElement) || !(fileInput instanceof HTMLInputElement)) {
      return;
    }
    const useXhr = options.useXhr !== false;

    let fallbackSubmitting = false;

    fileInput.addEventListener("change", () => {
      renderUploadTracker(statusRoot, fileInput.files, 0, false);
    });

    form.addEventListener("submit", (event) => {
      if (fallbackSubmitting) {
        return;
      }
      if (typeof validate === "function" && !validate()) {
        event.preventDefault();
        return;
      }
      const files = Array.from(fileInput.files || []);
      if (!files.length) {
        return;
      }
      if (!useXhr) {
        submitButton?.setAttribute("disabled", "disabled");
        renderUploadTracker(statusRoot, files, 0, false);
        const title = statusRoot?.querySelector?.("[data-upload-title]");
        const summary = statusRoot?.querySelector?.("[data-upload-summary]");
        if (title) {
          title.textContent = "Upload gestartet";
        }
        if (summary) {
          summary.textContent = "Bitte warten, die Titel werden verarbeitet.";
        }
        return;
      }

      event.preventDefault();
      submitButton?.setAttribute("disabled", "disabled");

      const request = new XMLHttpRequest();
      request.open(form.method || "POST", form.action || window.location.pathname);
      request.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      request.upload.addEventListener("progress", (progressEvent) => {
        if (!progressEvent.lengthComputable) {
          return;
        }
        renderUploadTracker(statusRoot, files, progressEvent.loaded / progressEvent.total, false);
      });
      request.addEventListener("load", () => {
        let payload = null;
        try {
          payload = JSON.parse(request.responseText || "{}");
        } catch (_error) {
          payload = null;
        }
        if (request.status >= 200 && request.status < 300 && (!payload || payload.ok !== false)) {
          renderUploadTracker(statusRoot, files, 1, true);
          window.setTimeout(() => window.location.reload(), 260);
          return;
        }
        submitButton?.removeAttribute("disabled");
        renderUploadError(statusRoot, files, extractUploadErrorMessage(request));
      });
      request.addEventListener("error", () => {
        submitButton?.removeAttribute("disabled");
        renderUploadError(statusRoot, files, "Upload-Verbindung abgebrochen. Bitte erneut versuchen.");
      });
      request.send(new FormData(form));
    });
  }

  function prettyTrackLabel(track) {
    const parts = String(track || "").split("/");
    const leaf = parts[parts.length - 1] || "";
    return leaf.replaceAll("_", " ");
  }

  function selectedTrackPaths() {
    if (!(trackList instanceof HTMLElement)) {
      return [];
    }
    return Array.from(trackList.querySelectorAll('input[type="checkbox"][data-track-path]:checked'))
      .map((entry) => entry.dataset.trackPath || "")
      .filter(Boolean);
  }

  function syncTrackSelectionState() {
    const selected = selectedTrackPaths();
    if (removeSelectedButton instanceof HTMLButtonElement) {
      removeSelectedButton.disabled = selected.length === 0;
      removeSelectedButton.textContent = selected.length > 0 ? `Ausgewählte entfernen (${selected.length})` : "Ausgewählte entfernen";
    }
    if (trackSelectionStatus instanceof HTMLElement) {
      trackSelectionStatus.textContent = selected.length > 0 ? `${selected.length} Titel ausgewählt` : "Keine Titel ausgewählt";
    }
  }

  async function removeSelectedTracks(album) {
    const selected = selectedTrackPaths();
    if (!album?.id || !selected.length) {
      syncTrackSelectionState();
      return;
    }

    if (removeSelectedButton instanceof HTMLButtonElement) {
      removeSelectedButton.disabled = true;
    }

    const formData = new FormData();
    formData.append("action", "remove_tracks");
    formData.append("album_id", album.id);
    for (const track of selected) {
      formData.append("track_path", track);
    }

    try {
      const response = await fetch("/library", {
        method: "POST",
        headers: {"X-Requested-With": "XMLHttpRequest"},
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        if (trackSelectionStatus instanceof HTMLElement) {
          trackSelectionStatus.textContent = payload?.message || "Titel konnten nicht entfernt werden.";
        }
        syncTrackSelectionState();
        return;
      }
      activeAlbum.track_entries = (activeAlbum.track_entries || []).filter((track) => !selected.includes(track));
      activeAlbum.track_count = Math.max(0, Number(activeAlbum.track_count || 0) - selected.length);
      renderTrackList(activeAlbum);
    } catch (_error) {
      if (trackSelectionStatus instanceof HTMLElement) {
        trackSelectionStatus.textContent = "Titel konnten nicht entfernt werden.";
      }
      syncTrackSelectionState();
    }
  }

  function renderTrackList(album) {
    if (!trackList) {
      return;
    }
    trackList.innerHTML = "";
    const tracks = album?.track_entries || [];
    if (!tracks.length) {
      const empty = document.createElement("p");
      empty.className = "page-copy";
      empty.textContent = "Keine Titel vorhanden.";
      trackList.appendChild(empty);
      return;
    }
    for (const track of tracks) {
      const row = document.createElement("div");
      row.className = "track-row";

      const selection = document.createElement("label");
      selection.className = "track-select";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.trackPath = track;
      checkbox.addEventListener("change", syncTrackSelectionState);

      const nameWrap = document.createElement("div");
      nameWrap.className = "track-name-wrap";

      const name = document.createElement("span");
      name.className = "track-display-name";
      name.textContent = prettyTrackLabel(track);

      const raw = document.createElement("span");
      raw.className = "mono track-raw-name";
      raw.textContent = track;

      nameWrap.appendChild(name);
      nameWrap.appendChild(raw);
      selection.appendChild(checkbox);
      selection.appendChild(nameWrap);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Entfernen";
      remove.addEventListener("click", async () => {
        checkbox.checked = true;
        syncTrackSelectionState();
        await removeSelectedTracks(album);
      });

      row.appendChild(selection);
      row.appendChild(remove);
      trackList.appendChild(row);
    }
    syncTrackSelectionState();
  }

  function openEditModal(albumId) {
    activeAlbum = findAlbum(albumId);
    if (!activeAlbum || !editModal) {
      return;
    }
    editTitle.textContent = "Bearbeiten";
    if (editCurrentName) {
      editCurrentName.textContent = `Album: ${activeAlbum.name}`;
    }
    addTracksAlbumId.value = activeAlbum.id;
    if (renameAlbumId) {
      renameAlbumId.value = activeAlbum.id;
    }
    if (renameFolder) {
      renameFolder.value = activeAlbum.folder || "";
    }
    if (renamePlaylist) {
      renamePlaylist.value = activeAlbum.playlist || "";
    }
    if (renameTrackCount) {
      renameTrackCount.value = activeAlbum.track_count || 0;
    }
    if (renameRfid) {
      renameRfid.value = activeAlbum.rfid_uid || "";
    }
    if (renameCover) {
      renameCover.value = activeAlbum.cover_url || "";
    }
    if (renameNameInput) {
      renameNameInput.value = activeAlbum.name || "";
    }
    if (renameWarning) {
      renameWarning.hidden = true;
    }
    if (trackInput) {
      trackInput.value = "";
    }
    renderUploadTracker(addUploadStatus, [], 0, false);
    renderTrackList(activeAlbum);
    showEditSection("home");
    editModal.showModal();
  }

  function showLinkView(view) {
    confirmView.hidden = view !== "confirm";
    unlinkFinalView.hidden = view !== "unlink-final";
  }

  function setConfirmMode(type, albumId, albumName) {
    pendingAction = type;
    activeAlbum = findAlbum(albumId) || {id: albumId, name: albumName, rfid_uid: ""};
    if (linkInput && type === "link") {
      linkInput.value = activeAlbum.rfid_uid || "";
    }
    restoreConfirmView();
    if (!linkModal.open) {
      linkModal.showModal();
    }
  }

  function syncConfirmState() {
    if (!confirmButton) {
      return;
    }
    if (pendingAction === "unlink") {
      confirmButton.disabled = false;
      return;
    }
    confirmButton.disabled = !(linkInput?.value || "").trim();
  }

  async function refreshStatus() {
    const response = await fetch("/api/library/link-session");
    const payload = await response.json();
    const session = payload.link_session || {};
    if (pendingAction !== "link") {
      return;
    }
    if ((session.last_uid || "").trim()) {
      linkInput.value = session.last_uid;
      syncConfirmState();
    }
    if (!session.active && session.status === "conflict") {
      stopPolling();
      confirmView.classList.add("link-warning-surface");
      messageText.textContent = session.message || "Tag bereits anderweitig verlinkt";
      syncConfirmState();
    }
  }

  async function startLinkSession(albumId) {
    const response = await fetch("/api/library/link-session", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({album_id: albumId}),
    });
    const payload = await response.json();
    if (!payload.ok) {
      messageText.textContent = payload.message || "Verlinkung konnte nicht gestartet werden.";
      return;
    }
    stopPolling();
    pollTimer = window.setInterval(refreshStatus, 1000);
  }

  async function submitLink(albumId, uid) {
    const response = await fetch("/api/library/link-session/confirm", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({album_id: albumId, uid}),
    });
    const payload = await response.json();
    if (!payload.ok) {
      messageText.textContent = payload.message || "Verlinkung konnte nicht gespeichert werden.";
      return;
    }
    stopPolling();
    pendingAction = null;
    linkModal.close();
    window.location.reload();
  }

  async function submitRuntimeAction(button) {
    const action = button.dataset.libraryRuntimeAction;
    const form = button.closest("form");
    const albumId = button.dataset.albumId || form?.querySelector("[name='album_id']")?.value || "";
    if (!action || !albumId || button.disabled) {
      return;
    }

    const endpoint = action === "queue" ? "/api/runtime/queue-album" : "/api/runtime/load-album";
    const payload = action === "queue" ? {album_id: albumId} : {album_id: albumId, autoplay: true};

    button.disabled = true;
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        return;
      }
      button.classList.add("library-action-success");
      window.setTimeout(() => button.classList.remove("library-action-success"), 600);
    } finally {
      button.disabled = false;
    }
  }

  async function submitCoverUpload(albumId, file) {
    if (!albumId || !(file instanceof File)) {
      return;
    }
    const data = new FormData();
    data.append("action", "replace_cover");
    data.append("album_id", albumId);
    data.append("cover_file", file);

    const response = await fetch("/library", {
      method: "POST",
      headers: {"X-Requested-With": "XMLHttpRequest"},
      body: data,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload?.message || "Cover konnte nicht hochgeladen werden.");
    }
  }

  function openDeleteModal(albumId, albumName) {
    pendingDeleteAlbum = {id: albumId, name: albumName};
    if (deleteAlbumName) {
      deleteAlbumName.textContent = `Album: ${albumName}`;
    }
    if (deleteAlbumId) {
      deleteAlbumId.value = albumId;
    }
    deleteModal?.showModal();
  }

  createOpenButton?.addEventListener("click", openCreateModal);
  createTrackTrigger?.addEventListener("click", () => createTrackInput?.click());
  trackTrigger?.addEventListener("click", () => trackInput?.click());
  createNameInput?.addEventListener("input", () => {
    const hasConflict = createNameExists(createNameInput.value);
    if (createWarning) {
      createWarning.hidden = !hasConflict;
    }
    createModalBody?.classList.toggle("create-warning-surface", hasConflict);
  });
  createForm?.addEventListener("submit", (event) => {
    if (!createNameExists(createNameInput?.value || "")) {
      return;
    }
    event.preventDefault();
    if (createWarning) {
      createWarning.hidden = false;
    }
    createModalBody?.classList.add("create-warning-surface");
    createNameInput?.focus();
  });
  bindCreateAlbumUpload(
    createForm,
    createTrackInput,
    createUploadStatus,
    createSubmitButton,
    () => !createNameExists(createNameInput?.value || "")
  );

  for (const closeButton of document.querySelectorAll("[data-close-create]")) {
    closeButton.addEventListener("click", closeCreateModal);
  }

  for (const button of document.querySelectorAll(".js-open-edit-modal")) {
    button.addEventListener("click", () => openEditModal(button.dataset.albumId));
  }

  document.getElementById("open-remove-tracks")?.addEventListener("click", () => showEditSection("remove"));
  document.getElementById("open-add-tracks")?.addEventListener("click", () => showEditSection("add"));
  document.getElementById("open-rename-album")?.addEventListener("click", () => {
    showEditSection("rename");
    window.setTimeout(() => renameNameInput?.focus(), 60);
  });
  renameNameInput?.addEventListener("input", () => {
    const hasConflict = renameNameExists(renameNameInput.value, renameAlbumId?.value || "");
    if (renameWarning) {
      renameWarning.hidden = !hasConflict;
    }
  });
  document.getElementById("album-rename-form")?.addEventListener("submit", (event) => {
    if (!renameNameExists(renameNameInput?.value || "", renameAlbumId?.value || "")) {
      return;
    }
    event.preventDefault();
    if (renameWarning) {
      renameWarning.hidden = false;
    }
    renameNameInput?.focus();
  });
  bindUploadProgress(addTracksForm, trackInput, addUploadStatus, addSubmitButton);
  removeSelectedButton?.addEventListener("click", async () => {
    await removeSelectedTracks(activeAlbum);
  });
  for (const button of document.querySelectorAll("[data-edit-back]")) {
    button.addEventListener("click", () => showEditSection("home"));
  }
  for (const button of document.querySelectorAll("[data-close-edit]")) {
    button.addEventListener("click", () => editModal?.close());
  }

  for (const button of document.querySelectorAll(".js-rfid-status-button")) {
    button.addEventListener("click", () => {
      const linked = button.dataset.linked === "true";
      const album = findAlbum(button.dataset.albumId) || {
        id: button.dataset.albumId,
        name: button.dataset.albumName,
        rfid_uid: button.dataset.rfidUid || "",
      };
      activeAlbum = album;
      setConfirmMode(linked ? "unlink" : "link", button.dataset.albumId, button.dataset.albumName);
      if (!linked) {
        startLinkSession(button.dataset.albumId);
      }
    });
  }

  for (const button of document.querySelectorAll("[data-library-runtime-action]")) {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      await submitRuntimeAction(button);
    });
  }

  for (const button of document.querySelectorAll("[data-cover-button]")) {
    button.addEventListener("click", () => {
      const albumId = button.dataset.albumId || "";
      const albumName = button.dataset.albumName || "dieses Album";
      if (!albumId || !(coverInput instanceof HTMLInputElement) || !(coverAlbumId instanceof HTMLInputElement)) {
        return;
      }
      const confirmed = window.confirm(`Cover für "${albumName}" ersetzen/hochladen?\nUnterstützt: JPG, PNG, WEBP, GIF, BMP.`);
      if (!confirmed) {
        return;
      }
      coverAlbumId.value = albumId;
      coverInput.value = "";
      coverInput.click();
    });
  }

  coverInput?.addEventListener("change", async () => {
    const albumId = coverAlbumId instanceof HTMLInputElement ? coverAlbumId.value : "";
    const file = coverInput.files?.[0];
    if (!albumId || !file) {
      return;
    }
    if (coverInput instanceof HTMLInputElement) {
      coverInput.disabled = true;
    }
    try {
      await submitCoverUpload(albumId, file);
      window.location.reload();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Cover konnte nicht hochgeladen werden.");
    } finally {
      if (coverInput instanceof HTMLInputElement) {
        coverInput.disabled = false;
      }
    }
  });

  for (const button of document.querySelectorAll("[data-delete-album-button]")) {
    button.addEventListener("click", () => {
      openDeleteModal(button.dataset.albumId || "", button.dataset.albumName || "");
    });
  }

  deleteCancel?.addEventListener("click", () => {
    pendingDeleteAlbum = null;
    deleteModal?.close();
  });

  deleteConfirm?.addEventListener("click", () => {
    if (!pendingDeleteAlbum?.id || !deleteForm) {
      return;
    }
    if (deleteAlbumId) {
      deleteAlbumId.value = pendingDeleteAlbum.id;
    }
    deleteForm.submit();
  });

  confirmButton?.addEventListener("click", async () => {
    if (!activeAlbum) {
      return;
    }
    if (pendingAction === "link") {
      const uid = (linkInput?.value || "").trim();
      if (!uid) {
        syncConfirmState();
        return;
      }
      await submitLink(activeAlbum.id, uid);
      return;
    }
    if (pendingAction === "unlink") {
      showLinkView("unlink-final");
    }
  });

  cancelButton?.addEventListener("click", () => {
    if (pendingAction === "link") {
      fetch("/api/library/link-session/cancel", {method: "POST"});
    }
    pendingAction = null;
    linkModal.close();
  });

  unlinkFinalConfirm?.addEventListener("click", () => {
    if (unlinkForm && unlinkAlbumId && activeAlbum) {
      unlinkAlbumId.value = activeAlbum.id;
      unlinkForm.submit();
    }
  });

  unlinkFinalCancel?.addEventListener("click", () => {
    pendingAction = null;
    linkModal.close();
  });

  linkInput?.addEventListener("input", syncConfirmState);

  linkModal?.addEventListener("close", () => {
    if (pendingAction === "link") {
      fetch("/api/library/link-session/cancel", {method: "POST"});
    }
    stopPolling();
    if (linkInput) {
      linkInput.value = "";
    }
    if (unlinkValue) {
      unlinkValue.textContent = "";
    }
    confirmView.classList.remove("link-warning-surface");
    messageText.textContent = "";
    pendingAction = null;
  });
});
