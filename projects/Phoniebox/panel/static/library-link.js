document.addEventListener("DOMContentLoaded", () => {
  const albumsPayload = document.getElementById("library-albums-json");
  const albums = albumsPayload ? JSON.parse(albumsPayload.textContent) : [];

  const createModal = document.getElementById("album-create-modal");
  const createModalBody = document.getElementById("album-create-modal-body");
  const createOpenButton = document.getElementById("open-album-create");
  const createNameInput = document.getElementById("album-create-name");
  const createWarning = document.getElementById("album-create-warning");
  const createForm = document.getElementById("album-create-form");
  const folderInput = document.getElementById("album-folder-input");
  const folderTrigger = document.getElementById("album-folder-trigger");

  const editModal = document.getElementById("album-edit-modal");
  const editTitle = document.getElementById("album-edit-title");
  const editCurrentName = document.getElementById("album-edit-current-name");
  const editHome = document.getElementById("album-edit-home");
  const editRename = document.getElementById("album-edit-rename");
  const editRemove = document.getElementById("album-edit-remove");
  const editAdd = document.getElementById("album-edit-add");
  const trackList = document.getElementById("album-track-list");
  const addTracksForm = document.getElementById("album-add-tracks-form");
  const addTracksAlbumId = document.getElementById("album-add-id");
  const trackInput = document.getElementById("album-track-input");
  const trackTrigger = document.getElementById("album-track-trigger");
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
    createModal.showModal();
    window.setTimeout(() => createNameInput?.focus(), 60);
  }

  function closeCreateModal() {
    createModal?.close();
  }

  function createNameExists(name) {
    const normalized = (name || "").trim().toLowerCase();
    return Boolean(normalized) && albums.some((entry) => (entry.name || "").trim().toLowerCase() === normalized);
  }

  function renameNameExists(name, albumId) {
    const normalized = (name || "").trim().toLowerCase();
    return Boolean(normalized) && albums.some((entry) => entry.id !== albumId && (entry.name || "").trim().toLowerCase() === normalized);
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

      const name = document.createElement("span");
      name.className = "mono";
      name.textContent = track;

      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Entfernen";
      remove.addEventListener("click", () => {
        const form = document.createElement("form");
        form.method = "post";
        form.className = "hidden-form";
        form.innerHTML = `
          <input type="hidden" name="action" value="remove_track">
          <input type="hidden" name="album_id" value="${album.id}">
          <input type="hidden" name="track_path" value="${track}">
        `;
        document.body.appendChild(form);
        form.submit();
      });

      row.appendChild(name);
      row.appendChild(remove);
      trackList.appendChild(row);
    }
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
    linkModal.close();
    window.location.reload();
  }

  async function submitRuntimeAction(button) {
    const action = button.dataset.libraryRuntimeAction;
    const albumId = button.dataset.albumId || button.closest("form")?.querySelector("[name='album_id']")?.value || "";
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
  folderTrigger?.addEventListener("click", () => folderInput?.click());
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
