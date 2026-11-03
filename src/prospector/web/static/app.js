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

  // Toasts: the server sends HX-Trigger {"toast": {msg, undo, target}} after each lead action.
  let toastTimer = null;
  function toastBox() {
    let box = document.getElementById("toast");
    if (!box) {
      box = document.createElement("div");
      box.id = "toast";
      box.className = "toast";
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
      document.body.appendChild(box);
    }
    return box;
  }
  function hideToast() { const b = document.getElementById("toast"); if (b) b.classList.remove("show"); }
  document.body.addEventListener("toast", (e) => {
    const { msg, undo, target } = e.detail;
    const box = toastBox();
    box.replaceChildren(document.createTextNode(msg));
    if (undo) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "toast-undo";
      btn.textContent = "Undo";
      btn.addEventListener("click", () => {
        hideToast();
        htmx.ajax("POST", undo, { target, swap: "outerHTML", headers: { "HX-Target": target.slice(1) } });
      });
      box.append(" ", btn);
    }
    box.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, 6000);
  });
  window.prospectorUndo = () => document.querySelector("#toast.show .toast-undo")?.click();

  // Keyboard shortcuts (see the ? overlay in base.html).
  const shortcuts = () => document.getElementById("shortcuts");
  function toggleShortcuts(force) {
    const el = shortcuts();
    if (el) el.hidden = force === undefined ? !el.hidden : !force;
  }
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-toggle-shortcuts]")) toggleShortcuts();
    else if (e.target === shortcuts()) toggleShortcuts(false);
  });

  const leads = () => [...document.querySelectorAll(".lead")];
  function current() {
    const active = document.activeElement?.closest?.(".lead");
    return active || null;
  }
  function move(step) {
    const all = leads();
    if (!all.length) return;
    const i = all.indexOf(current());
    const next = all[Math.min(all.length - 1, Math.max(0, i === -1 ? 0 : i + step))];
    next.focus();
    next.scrollIntoView({ block: "nearest" });
  }
  function press(cls) {
    const row = current() || document.getElementById("detail-actions")?.parentElement;
    row?.querySelector(cls)?.click();
  }

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t.closest?.("input, textarea, select, [contenteditable]")) {
      if (e.key === "Escape") t.blur();
      return;
    }
    const keys = {
      j: () => move(1), k: () => move(-1),
      s: () => press(".act-star"), a: () => press(".act-applied"), d: () => press(".act-dismiss"),
      u: () => window.prospectorUndo(),
      o: () => { const url = current()?.dataset.url || document.querySelector(".detail-bar a.btn-primary")?.href;
                 if (url) window.open(url, "_blank", "noopener"); },
      "/": () => document.getElementById("search")?.focus(),
      "?": () => toggleShortcuts(),
      Escape: () => toggleShortcuts(false),
      Enter: () => { const a = current()?.querySelector(".lead-title"); if (a && t === current()) a.click(); },
    };
    const fn = keys[e.key];
    if (fn) { e.preventDefault(); fn(); }
  });

  function rowIndex(row) {
    const m = row.querySelector("[name]")?.name.match(/\[(\d+)\]/);
    return m ? Number(m[1]) : 0;
  }
})();
