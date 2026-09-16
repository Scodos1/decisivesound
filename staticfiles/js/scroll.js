document.addEventListener("DOMContentLoaded", () => {
  const revealEls = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
            obs.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15 }
    );
    revealEls.forEach((el) => obs.observe(el));
  } else {
    revealEls.forEach((el) => el.classList.add("visible"));
  }

  // Sticky "Book Now" button appears after scrolling past the hero
  const stickyBook = document.querySelector(".sticky-book");
  if (stickyBook) {
    window.addEventListener("scroll", () => {
      if (window.scrollY > 700) stickyBook.classList.add("show");
      else stickyBook.classList.remove("show");
    });
  }
});
