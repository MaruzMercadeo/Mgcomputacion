document.addEventListener("DOMContentLoaded", () => {
  const flashes = document.querySelectorAll(".alert");
  flashes.forEach((item) => {
    setTimeout(() => item.classList.add("fade-out"), 4500);
  });
});
