document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("rfid-link-modal");
  if (!modal) {
    return;
  }

  const albumText = document.getElementById("rfid-link-album");
  const messageText = document.getElementById("rfid-link-message");
  const cancelButton = document.getElementById("rfid-link-cancel");
  let pollTimer = null;

  function stopPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function refreshStatus() {
    const response = await fetch("/api/library/link-session");
    const payload = await response.json();
    const session = payload.link_session || {};
    if (!session.active) {
      if (session.status === "linked") {
        messageText.innerHTML = `<strong>${session.message}</strong><br><span>UID: ${session.last_uid}</span>`;
        stopPolling();
        window.setTimeout(() => window.location.reload(), 900);
        return;
      }
      if (session.status === "conflict") {
        messageText.innerHTML = `<strong>${session.message}</strong><br><span>UID: ${session.last_uid}</span>`;
        stopPolling();
        return;
      }
      if (session.status === "cancelled") {
        messageText.innerHTML = `<strong>${session.message}</strong>`;
        stopPolling();
        return;
      }
    }
    messageText.innerHTML = `<strong>${session.message || "Jetzt Tag scannen"}</strong>`;
  }

  async function startLink(albumId, albumName) {
    const response = await fetch("/api/library/link-session", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({album_id: albumId}),
    });
    const payload = await response.json();
    if (!payload.ok) {
      messageText.innerHTML = `<strong>${payload.message || "Verlinkung konnte nicht gestartet werden."}</strong>`;
      return;
    }
    albumText.textContent = `Album: ${albumName}`;
    messageText.innerHTML = "<strong>Jetzt Tag scannen</strong>";
    modal.showModal();
    stopPolling();
    pollTimer = window.setInterval(refreshStatus, 1000);
  }

  for (const button of document.querySelectorAll(".js-open-link-modal")) {
    button.addEventListener("click", () => {
      startLink(button.dataset.albumId, button.dataset.albumName);
    });
  }

  cancelButton?.addEventListener("click", async () => {
    await fetch("/api/library/link-session/cancel", {method: "POST"});
    await refreshStatus();
    modal.close();
  });

  for (const closeButton of document.querySelectorAll("[data-close-modal]")) {
    closeButton.addEventListener("click", async () => {
      await fetch("/api/library/link-session/cancel", {method: "POST"});
      stopPolling();
      modal.close();
    });
  }

  modal.addEventListener("close", stopPolling);
});
