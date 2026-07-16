document.addEventListener("DOMContentLoaded", () => {
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Glass-card cursor spotlight ---------- */
  // Tracks the pointer over any .glass-card and feeds its position into
  // CSS custom properties so the ::before spotlight (see enhance.css) can follow it.
  if (!prefersReducedMotion) {
    document.addEventListener("pointermove", (e) => {
      const card = e.target.closest(".glass-card");
      if (!card) return;
      const rect = card.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      card.style.setProperty("--mx", x + "%");
      card.style.setProperty("--my", y + "%");
    });
  }

  /* ---------- Magnetic primary buttons ---------- */
  // Subtle pull-toward-cursor effect on the main CTAs, reset smoothly on leave.
  if (!prefersReducedMotion) {
    const magneticSelector = ".btn-primary, .btn-solid";
    document.querySelectorAll(magneticSelector).forEach((btn) => {
      const strength = 0.18;
      btn.addEventListener("pointermove", (e) => {
        const rect = btn.getBoundingClientRect();
        const relX = e.clientX - (rect.left + rect.width / 2);
        const relY = e.clientY - (rect.top + rect.height / 2);
        btn.style.transform = `translate(${relX * strength}px, ${relY * strength}px)`;
      });
      btn.addEventListener("pointerleave", () => {
        btn.style.transform = "";
      });
    });
  }

  /* ---------- Auto-scrolling reviews marquee ---------- */
  const reviews = document.querySelector(".reviews-scroll");
  if (reviews && !prefersReducedMotion) {
    let paused = false;
    let rafId = null;
    const speed = 0.45; // px per frame, gentle

    reviews.addEventListener("pointerenter", () => (paused = true));
    reviews.addEventListener("pointerleave", () => (paused = false));
    reviews.addEventListener("touchstart", () => (paused = true), { passive: true });
    reviews.addEventListener("touchend", () => (paused = false));

    const step = () => {
      if (!paused) {
        const maxScroll = reviews.scrollWidth - reviews.clientWidth;
        if (maxScroll > 0) {
          if (reviews.scrollLeft >= maxScroll - 1) {
            reviews.scrollLeft = 0;
          } else {
            reviews.scrollLeft += speed;
          }
        }
      }
      rafId = requestAnimationFrame(step);
    };
    rafId = requestAnimationFrame(step);

    // Pause the automatic scroll once a person starts dragging/scrolling manually,
    // resume shortly after they stop.
    let resumeTimer = null;
    reviews.addEventListener("wheel", () => {
      paused = true;
      clearTimeout(resumeTimer);
      resumeTimer = setTimeout(() => (paused = false), 2500);
    }, { passive: true });
  }
});

/* ============================================================
   PREMIUM CUSTOM SELECT DROPDOWNS
   Wraps every <select> in a .select-wrap with a .select-face
   so we can style it with glassmorphism while keeping the
   native <select> functional for form submission and a11y.
   ============================================================ */
(function initCustomSelects() {
  function buildFace(select) {
    // Already wrapped?
    if (select.closest('.select-wrap')) return;

    const wrap = document.createElement('div');
    wrap.className = 'select-wrap';

    // Move select into wrap
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);

    // Build the visible face
    const face = document.createElement('div');
    face.className = 'select-face';

    const textEl = document.createElement('span');
    textEl.className = 'select-face-text';
    textEl.textContent = select.options[select.selectedIndex]?.text || '';

    const arrow = document.createElement('span');
    arrow.className = 'select-face-arrow';
    arrow.innerHTML = '<span class="material-symbols-outlined">expand_more</span>';

    face.appendChild(textEl);
    face.appendChild(arrow);
    wrap.appendChild(face);

    // Keep label in sync when user picks an option
    select.addEventListener('change', () => {
      textEl.textContent = select.options[select.selectedIndex]?.text || '';
    });
  }

  function initAll() {
    // Skip selects that are part of the nav mobile (they're links, not form controls)
    document.querySelectorAll('select').forEach(buildFace);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
