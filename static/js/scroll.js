document.addEventListener("DOMContentLoaded", () => {
  // Sticky "Book Now" button appears after scrolling past the hero
  const stickyBook = document.querySelector(".sticky-book");
  if (stickyBook) {
    window.addEventListener("scroll", () => {
      if (window.scrollY > 700) stickyBook.classList.add("show");
      else stickyBook.classList.remove("show");
    });
  }
});
