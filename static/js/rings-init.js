document.addEventListener("DOMContentLoaded", () => {
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Homepage hero — the big signature moment ---------- */
  const heroRingsEl = document.getElementById("hero-rings");
  if (heroRingsEl && !prefersReducedMotion && window.MagicRings) {
    const heroRings = window.MagicRings.create(heroRingsEl, {
      color: "#f0a8d9",       // brand lavender
      colorTwo: "#e8823c",    // brand cyan
      ringCount: 6,
      speed: 0.8,
      attenuation: 9,
      lineThickness: 2,
      baseRadius: 0.22,
      radiusStep: 0.09,
      scaleRate: 0.12,
      opacity: 0.55,
      noiseAmount: 0.06,
      ringGap: 1.4,
      followMouse: true,
      mouseInfluence: 0.12,
      parallax: 0.04,
      clickBurst: false,
    });

    // Tie the rings' presence to scroll position: fade + drift slightly
    // as the person scrolls past the hero, so it reads as one continuous
    // scroll animation rather than a static backdrop.
    let ticking = false;
    window.addEventListener("scroll", () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        const y = window.scrollY;
        const fade = Math.max(0, 1 - y / 700);
        heroRingsEl.style.transform = `translateY(${y * 0.15}px)`;
        heroRings.setOpacity(fade);
        ticking = false;
      });
    }, { passive: true });
  }

  /* ---------- Interior page heroes — quieter echo of the same signature ---------- */
  if (!prefersReducedMotion && window.MagicRings) {
    document.querySelectorAll(".page-hero-rings").forEach((el) => {
      window.MagicRings.create(el, {
        color: "#f0a8d9",
        colorTwo: "#e8823c",
        ringCount: 3,
        speed: 0.6,
        attenuation: 11,
        lineThickness: 1.5,
        baseRadius: 0.3,
        radiusStep: 0.12,
        scaleRate: 0.1,
        opacity: 0.4,
        noiseAmount: 0.05,
        followMouse: false,
        clickBurst: false,
      });
    });
  }

  /* ---------- Ring-burst click feedback, everywhere a .btn exists ---------- */
  // A small, cheap CSS/JS echo of the rings motif for buttons — no WebGL,
  // just two concentric rings expanding + fading from the click point.
  if (!prefersReducedMotion) {
    document.addEventListener("pointerdown", (e) => {
      const btn = e.target.closest(".btn");
      if (!btn) return;
      const rect = btn.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      for (let i = 0; i < 2; i++) {
        const ring = document.createElement("span");
        ring.className = "ring-burst";
        ring.style.left = x + "px";
        ring.style.top = y + "px";
        ring.style.animationDelay = i * 0.1 + "s";
        btn.appendChild(ring);
        ring.addEventListener("animationend", () => ring.remove());
      }
    });
  }
});
