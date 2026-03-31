document.addEventListener("DOMContentLoaded", () => {
  let draggedFunction = "";
  let selectedChip = null;

  function emptyLabel(slot) {
    return slot.dataset.emptyLabel || "Funktion hierhin ziehen";
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
});
