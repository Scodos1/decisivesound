// Update WA_NUMBER once here and every WhatsApp button/link on the site updates with it.
const WA_NUMBER = "2348033807067"; // Decisive Sound NG WhatsApp number
const WA_DEFAULT_MESSAGE = "Hi Decisive Sound NG, I'd like to book silent headsets for my event.";

function buildWaLink(message) {
  const text = encodeURIComponent(message || WA_DEFAULT_MESSAGE);
  return `https://wa.me/${WA_NUMBER}?text=${text}`;
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-wa-link]").forEach((el) => {
    const customMsg = el.getAttribute("data-wa-message");
    el.setAttribute("href", buildWaLink(customMsg));
  });
});
