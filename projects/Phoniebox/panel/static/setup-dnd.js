document.addEventListener("DOMContentLoaded", () => {
  let draggedFunction = "";

  for (const chip of document.querySelectorAll("[data-function-chip]")) {
    chip.addEventListener("dragstart", (event) => {
      draggedFunction = chip.dataset.functionChip || "";
      event.dataTransfer?.setData("text/plain", draggedFunction);
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
      const hidden = slot.querySelector("input[type='hidden']");
      const label = slot.querySelector("[data-drop-label]");
      if (hidden) {
        hidden.value = dropped;
      }
      if (label) {
        label.textContent = dropped || "Funktion hierhin ziehen";
      }
      slot.classList.remove("drag-over");
    });

    slot.addEventListener("dblclick", () => {
      const hidden = slot.querySelector("input[type='hidden']");
      const label = slot.querySelector("[data-drop-label]");
      if (hidden) {
        hidden.value = "";
      }
      if (label) {
        label.textContent = "Funktion hierhin ziehen";
      }
    });
  }
});
