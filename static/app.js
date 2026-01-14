(() => {
  const shell = document.querySelector(".app-shell");
  if (!shell) return;

  const applyTheme = (theme) => {
    shell.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("schoolhub-theme", theme);
    } catch {}
  };

  const readTheme = () => {
    try {
      return localStorage.getItem("schoolhub-theme");
    } catch {
      return null;
    }
  };

  const saved = readTheme();
  if (saved === "light" || saved === "dark") applyTheme(saved);

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.getAttribute("data-action");
    if (action === "toggle-theme") {
      const current = shell.getAttribute("data-theme") || "dark";
      applyTheme(current === "dark" ? "light" : "dark");
    }
    if (action === "toggle-nav") {
      document.body.classList.toggle("nav-open");
    }
  });
})();

