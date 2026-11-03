// Prospector dashboard behaviour. Vanilla JS; HTMX does the requests.
(() => {
  "use strict";

  // Profile editor: add / remove repeating rows (skills, projects, min pay, boosts).
  document.addEventListener("click", (e) => {
    const add = e.target.closest("[data-add-row]");
    if (add) {
      const group = add.closest(".rows");
      const rows = group.querySelectorAll("[data-row]");
      const last = rows[rows.length - 1];
      const next = Math.max(-1, ...[...rows].map(rowIndex)) + 1;
      const clone = last.cloneNode(true);
      clone.querySelectorAll("input, textarea, select").forEach((el) => {
        el.name = el.name.replace(/\[\d+\]/, `[${next}]`);
        if (el.tagName === "SELECT") el.selectedIndex = Math.max(0, [...el.options].findIndex((o) => o.value === "year"));
        else el.value = "";
      });
      last.after(clone);
      clone.querySelector("input, textarea")?.focus();
      return;
    }
    const remove = e.target.closest("[data-remove-row]");
    if (remove) {
      const row = remove.closest("[data-row]");
      if (row.parentElement.querySelectorAll("[data-row]").length > 1) row.remove();
      else row.querySelectorAll("input, textarea").forEach((el) => { el.value = ""; });
    }
  });

  function rowIndex(row) {
    const m = row.querySelector("[name]")?.name.match(/\[(\d+)\]/);
    return m ? Number(m[1]) : 0;
  }
})();
