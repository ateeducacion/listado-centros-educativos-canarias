// Light/dark toggle shared by every page. Loaded in <head> so the stored
// choice applies before the first paint.
(function () {
  var KEY = "centres-theme";
  var root = document.documentElement;
  var stored = null;
  try {
    stored = window.localStorage.getItem(KEY);
  } catch (error) {
    stored = null;
  }
  if (stored === "light" || stored === "dark") {
    root.setAttribute("data-theme", stored);
  }

  function current() {
    var explicit = root.getAttribute("data-theme");
    if (explicit) return explicit;
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    button.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        window.localStorage.setItem(KEY, next);
      } catch (error) {
        // Storage may be unavailable; the choice then lasts for this page.
      }
    });
  });
})();
