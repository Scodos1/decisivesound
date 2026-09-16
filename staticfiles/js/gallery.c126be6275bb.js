// Powers the fullscreen lightbox for the Gallery page and the homepage
// gallery preview. Every ".gallery-item" (see templates/booking/_gallery_item.html)
// carries data-media-type/data-src/data-poster/data-caption attributes;
// clicking or pressing Enter/Space on one opens it full-viewport here, with
// left/right navigation between the other items on the same page and a
// native-fullscreen toggle for both photos and videos.
(function () {
  var items = Array.prototype.slice.call(document.querySelectorAll(".gallery-item[data-src]"));
  if (!items.length) return;

  var currentIndex = -1;
  var lightbox, stage, closeBtn, prevBtn, nextBtn, fullscreenBtn, captionEl;

  function buildLightbox() {
    lightbox = document.createElement("div");
    lightbox.className = "gallery-lightbox";
    lightbox.setAttribute("role", "dialog");
    lightbox.setAttribute("aria-modal", "true");
    lightbox.innerHTML =
      '<div class="gallery-lightbox-stage">' +
        '<div class="gallery-lightbox-controls">' +
          '<button type="button" class="gallery-lightbox-btn" data-action="fullscreen" aria-label="Toggle fullscreen">' +
            '<span class="material-symbols-outlined">fullscreen</span>' +
          '</button>' +
          '<button type="button" class="gallery-lightbox-btn" data-action="close" aria-label="Close">' +
            '<span class="material-symbols-outlined">close</span>' +
          '</button>' +
        '</div>' +
        '<button type="button" class="gallery-lightbox-nav prev" data-action="prev" aria-label="Previous">' +
          '<span class="material-symbols-outlined">chevron_left</span>' +
        '</button>' +
        '<button type="button" class="gallery-lightbox-nav next" data-action="next" aria-label="Next">' +
          '<span class="material-symbols-outlined">chevron_right</span>' +
        '</button>' +
        '<div class="gallery-lightbox-media"></div>' +
        '<div class="gallery-lightbox-caption"></div>' +
      '</div>';
    document.body.appendChild(lightbox);

    stage = lightbox.querySelector(".gallery-lightbox-media");
    captionEl = lightbox.querySelector(".gallery-lightbox-caption");
    closeBtn = lightbox.querySelector('[data-action="close"]');
    prevBtn = lightbox.querySelector('[data-action="prev"]');
    nextBtn = lightbox.querySelector('[data-action="next"]');
    fullscreenBtn = lightbox.querySelector('[data-action="fullscreen"]');

    lightbox.addEventListener("click", function (e) {
      if (e.target === lightbox) close();
    });
    closeBtn.addEventListener("click", close);
    prevBtn.addEventListener("click", function () { show(currentIndex - 1); });
    nextBtn.addEventListener("click", function () { show(currentIndex + 1); });
    fullscreenBtn.addEventListener("click", toggleFullscreen);

    document.addEventListener("keydown", function (e) {
      if (!lightbox.classList.contains("is-open")) return;
      if (e.key === "Escape") close();
      if (e.key === "ArrowLeft") show(currentIndex - 1);
      if (e.key === "ArrowRight") show(currentIndex + 1);
    });

    // Swipe left/right to move between items, so mobile visitors can
    // browse the lightbox naturally instead of only tapping the arrows.
    var stageEl = lightbox.querySelector(".gallery-lightbox-stage");
    var touchStartX = 0, touchStartY = 0;
    var SWIPE_THRESHOLD = 40; // px - low enough to feel responsive, high enough to ignore taps/scroll jitter

    stageEl.addEventListener("touchstart", function (e) {
      var t = e.changedTouches[0];
      touchStartX = t.clientX;
      touchStartY = t.clientY;
    }, { passive: true });

    stageEl.addEventListener("touchend", function (e) {
      var t = e.changedTouches[0];
      var deltaX = t.clientX - touchStartX;
      var deltaY = t.clientY - touchStartY;
      // Only treat it as a swipe if the motion is mostly horizontal -
      // otherwise a vertical swipe (e.g. scrubbing a video, or an
      // incidental vertical drag) would incorrectly change the item.
      if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > SWIPE_THRESHOLD) {
        if (deltaX < 0) show(currentIndex + 1);
        else show(currentIndex - 1);
      }
    }, { passive: true });
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen();
      return;
    }
    var target = lightbox.querySelector(".gallery-lightbox-stage");
    if (target.requestFullscreen) target.requestFullscreen().catch(function () {});
  }

  function show(index) {
    if (!items.length) return;
    currentIndex = (index + items.length) % items.length;
    var el = items[currentIndex];
    var type = el.getAttribute("data-media-type");
    var src = el.getAttribute("data-src");
    var poster = el.getAttribute("data-poster");
    var caption = el.getAttribute("data-caption") || "";

    stage.innerHTML = "";
    if (type === "video") {
      var video = document.createElement("video");
      video.src = src;
      if (poster) video.poster = poster;
      video.controls = true;
      video.autoplay = true;
      video.playsInline = true;
      stage.appendChild(video);
    } else {
      var img = document.createElement("img");
      img.src = src;
      img.alt = caption;
      stage.appendChild(img);
    }
    captionEl.textContent = caption;
    prevBtn.style.display = items.length > 1 ? "" : "none";
    nextBtn.style.display = items.length > 1 ? "" : "none";
  }

  function open(index) {
    if (!lightbox) buildLightbox();
    show(index);
    lightbox.classList.add("is-open");
    document.body.style.overflow = "hidden";
  }

  function close() {
    if (!lightbox) return;
    lightbox.classList.remove("is-open");
    document.body.style.overflow = "";
    if (document.fullscreenElement) document.exitFullscreen();
    // Stop any playing video and drop its src so audio doesn't keep running.
    var video = stage.querySelector("video");
    if (video) { video.pause(); video.removeAttribute("src"); video.load(); }
    stage.innerHTML = "";
  }

  items.forEach(function (el, index) {
    el.addEventListener("click", function () { open(index); });
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open(index);
      }
    });
  });
})();