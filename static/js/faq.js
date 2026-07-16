// FAQ now uses native <details> elements — no JS needed for the toggle itself.
// This script just ensures only one FAQ is open at a time.
document.addEventListener("DOMContentLoaded", () => {
  const details = document.querySelectorAll(".faq-details");
  details.forEach((detail) => {
    detail.addEventListener("toggle", () => {
      if (detail.open) {
        details.forEach((other) => {
          if (other !== detail) other.removeAttribute("open");
        });
      }
    });
  });
});
