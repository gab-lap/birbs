// ====== ANTEPRIMA UPLOAD ======
(function () {
  const input = document.getElementById("photoInput");
  const wrap = document.getElementById("previewWrap");
  const img = document.getElementById("previewImg");

  if (!input || !wrap || !img) return;

  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (!file) {
      wrap.classList.add("d-none");
      img.removeAttribute("src");
      return;
    }
    const url = URL.createObjectURL(file);
    img.src = url;
    wrap.classList.remove("d-none");
  });

  // reset anteprima quando chiudi il modal
  const uploadModal = document.getElementById("uploadModal");
  if (uploadModal) {
    uploadModal.addEventListener("hidden.bs.modal", () => {
      input.value = "";
      if (img.src) URL.revokeObjectURL(img.src);
      img.removeAttribute("src");
      wrap.classList.add("d-none");
    });
  }
})();

// ====== IMAGE VIEWER (lightbox) ======
(function () {
  const viewerModalEl = document.getElementById("imgViewer");
  const viewerImg = document.getElementById("viewerImg");
  const zoomWrap = document.getElementById("zoomWrap");
  const zoomInBtn = document.getElementById("zoomInBtn");
  const zoomOutBtn = document.getElementById("zoomOutBtn");
  const zoomResetBtn = document.getElementById("zoomResetBtn");

  if (!viewerModalEl || !viewerImg || !zoomWrap) return;

  // Apri modal quando clicchi su una .gallery-img
  document.addEventListener("click", (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    if (t.classList.contains("gallery-img")) {
      const full = t.getAttribute("data-fullsrc") || t.getAttribute("src");
      if (full) {
        viewerImg.src = full;
        resetTransform();
        const modal = bootstrap.Modal.getOrCreateInstance(viewerModalEl);
        modal.show();
      }
    }
  });

  // Stato zoom/pan
  let scale = 1;
  let originX = 0;
  let originY = 0;
  let posX = 0;
  let posY = 0;

  function applyTransform() {
    viewerImg.style.transformOrigin = `${originX}px ${originY}px`;
    viewerImg.style.transform = `translate(${posX}px, ${posY}px) scale(${scale})`;
    viewerImg.style.transition = "transform 0.05s linear";
  }

  function resetTransform() {
    scale = 1;
    posX = 0;
    posY = 0;
    originX = viewerImg.clientWidth / 2;
    originY = viewerImg.clientHeight / 2;
    applyTransform();
  }

  // Pulsanti zoom
  zoomInBtn?.addEventListener("click", () => {
    scale = Math.min(scale * 1.2, 6);
    applyTransform();
  });
  zoomOutBtn?.addEventListener("click", () => {
    scale = Math.max(scale / 1.2, 1);
    if (scale === 1) { posX = 0; posY = 0; }
    applyTransform();
  });
  zoomResetBtn?.addEventListener("click", resetTransform);

  // Drag per panning (desktop)
  let dragging = false;
  let startX = 0, startY = 0;

  viewerImg.addEventListener("mousedown", (e) => {
    if (scale <= 1) return;
    dragging = true;
    startX = e.clientX - posX;
    startY = e.clientY - posY;
    viewerImg.style.cursor = "grabbing";
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    posX = e.clientX - startX;
    posY = e.clientY - startY;
    applyTransform();
  });
  window.addEventListener("mouseup", () => {
    dragging = false;
    viewerImg.style.cursor = "";
  });

  // Wheel zoom (desktop)
  zoomWrap.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = viewerImg.getBoundingClientRect();
    originX = e.clientX - rect.left;
    originY = e.clientY - rect.top;
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    const newScale = Math.min(Math.max(scale * delta, 1), 6);
    // mantieni il punto sotto il cursore
    const factor = newScale / scale;
    posX = (posX - originX) * factor + originX;
    posY = (posY - originY) * factor + originY;
    scale = newScale;
    if (scale === 1) { posX = 0; posY = 0; }
    applyTransform();
  }, { passive: false });

  // Pinch-zoom (mobile) molto semplice
  let pinch = { active: false, dist: 0, midX: 0, midY: 0 };

  zoomWrap.addEventListener("touchstart", (e) => {
    if (e.touches.length === 2) {
      pinch.active = true;
      pinch.dist = distance(e.touches[0], e.touches[1]);
      const rect = viewerImg.getBoundingClientRect();
      pinch.midX = ((e.touches[0].clientX + e.touches[1].clientX) / 2) - rect.left;
      pinch.midY = ((e.touches[0].clientY + e.touches[1].clientY) / 2) - rect.top;
      originX = pinch.midX;
      originY = pinch.midY;
    } else if (e.touches.length === 1) {
      // pan con un dito quando zoom > 1
      if (scale > 1) {
        dragging = true;
        startX = e.touches[0].clientX - posX;
        startY = e.touches[0].clientY - posY;
      }
    }
  }, { passive: false });

  zoomWrap.addEventListener("touchmove", (e) => {
    if (pinch.active && e.touches.length === 2) {
      e.preventDefault();
      const d = distance(e.touches[0], e.touches[1]);
      const factor = d / pinch.dist;
      const newScale = Math.min(Math.max(scale * factor, 1), 6);

      const rect = viewerImg.getBoundingClientRect();
      const midX = ((e.touches[0].clientX + e.touches[1].clientX) / 2) - rect.left;
      const midY = ((e.touches[0].clientY + e.touches[1].clientY) / 2) - rect.top;

      originX = midX; originY = midY;

      const scaleFactor = newScale / scale;
      posX = (posX - originX) * scaleFactor + originX;
      posY = (posY - originY) * scaleFactor + originY;

      scale = newScale;
      if (scale === 1) { posX = 0; posY = 0; }
      applyTransform();

      pinch.dist = d;
    } else if (dragging && e.touches.length === 1) {
      e.preventDefault();
      posX = e.touches[0].clientX - startX;
      posY = e.touches[0].clientY - startY;
      applyTransform();
    }
  }, { passive: false });

  zoomWrap.addEventListener("touchend", () => {
    if (pinch.active) pinch.active = false;
    dragging = false;
  });

  function distance(a, b) {
    const dx = a.clientX - b.clientX;
    const dy = a.clientY - b.clientY;
    return Math.hypot(dx, dy);
  }

  // Quando si chiude il modal, reset
  viewerModalEl.addEventListener("hidden.bs.modal", resetTransform);
})();
