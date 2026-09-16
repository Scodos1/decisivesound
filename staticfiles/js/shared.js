// Shared nav active-link highlighter
document.addEventListener("DOMContentLoaded", () => {
  const path = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".nav-links a, .nav-mobile a").forEach((a) => {
    const href = a.getAttribute("href") || "";
    if (href === path) a.classList.add("active");
    else a.classList.remove("active");
  });
});
