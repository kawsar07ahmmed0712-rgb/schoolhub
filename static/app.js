(() => {
  const shell = document.querySelector(".app-shell");
  if (!shell) return;
  const sidebar = document.querySelector("[data-nav]");

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
  if (saved === "light" || saved === "dark") {
    applyTheme(saved);
  } else {
    // Default: dark to match the new visual direction; users can toggle.
    applyTheme("dark");
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (btn) {
      const action = btn.getAttribute("data-action");
      if (action === "toggle-theme") {
        const current = shell.getAttribute("data-theme") || "dark";
        applyTheme(current === "dark" ? "light" : "dark");
      }
      if (action === "toggle-nav") {
        document.body.classList.toggle("nav-open");
      }
    }

    if (document.body.classList.contains("nav-open")) {
      const clickedNavBtn = !!e.target.closest('[data-action="toggle-nav"]');
      const clickedInsideSidebar = sidebar ? !!e.target.closest("[data-nav]") : false;
      const clickedNavLink = !!e.target.closest(".nav-link");

      if (clickedNavLink || (!clickedNavBtn && !clickedInsideSidebar)) {
        document.body.classList.remove("nav-open");
      }
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      document.body.classList.remove("nav-open");
    }
  });

  const menuSearch = document.querySelector("[data-menu-search]");
  if (menuSearch) {
    const items = Array.from(document.querySelectorAll("[data-menu-item]"));
    const countEl = document.querySelector("[data-menu-count]");

    const update = () => {
      const q = (menuSearch.value || "").trim().toLowerCase();
      let shown = 0;
      for (const el of items) {
        const text = (el.getAttribute("data-menu-text") || el.textContent || "").toLowerCase();
        const visible = !q || text.includes(q);
        el.style.display = visible ? "" : "none";
        if (visible) shown += 1;
      }
      if (countEl) countEl.textContent = String(shown);
    };

    menuSearch.addEventListener("input", update);
    update();
  }

  const sheetSearch = document.querySelector("[data-sheet-search]");
  if (sheetSearch) {
    const rows = Array.from(document.querySelectorAll("[data-sheet-row]"));
    const countEl = document.querySelector("[data-sheet-count]");

    const update = () => {
      const q = (sheetSearch.value || "").trim().toLowerCase();
      let shown = 0;
      for (const row of rows) {
        const text = (row.getAttribute("data-sheet-text") || row.textContent || "").toLowerCase();
        const visible = !q || text.includes(q);
        row.style.display = visible ? "" : "none";
        if (visible) shown += 1;
      }
      if (countEl) countEl.textContent = String(shown);
    };

    sheetSearch.addEventListener("input", update);
    update();
  }
})();
