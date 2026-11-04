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
      clone.querySelectorAll(".chip-input").forEach((el) => el.remove());  // rebuilt below
      clone.querySelectorAll("input[data-chips]").forEach((el) => { el.type = "text"; delete el.dataset.chipsReady; });
      clone.querySelectorAll(".interest-preview").forEach((el) => { el.textContent = ""; });
      clone.querySelectorAll("input, textarea, select").forEach((el) => {
        if (!el.name) return;
        el.name = el.name.replace(/\[\d+\]/, `[${next}]`);
        if (el.tagName === "SELECT") el.selectedIndex = Math.max(0, [...el.options].findIndex((o) => o.value === "year"));
        else if (el.type === "number" && el.name.endsWith("[weight]")) el.value = "0.5";
        else if (el.type !== "checkbox") el.value = "";
      });
      if (clone.tagName === "DETAILS") clone.open = true;
      clone.classList.add("row-blank");
      last.classList.remove("row-blank");
      last.after(clone);
      initChips(clone);
      if (window.htmx) htmx.process(clone);
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
      // Only when a lead row itself has focus; links and buttons keep their own Enter.
      Enter: () => { const a = current()?.querySelector(".lead-title"); if (!a || t !== current()) return false; a.click(); },
    };
    const fn = keys[e.key];
    if (fn && fn() !== false) e.preventDefault();
  });

  // Lead assistant: Enter sends (Shift+Enter for a new line), live character count, copy buttons.
  document.addEventListener("keydown", (e) => {
    const box = e.target.closest?.("[data-enter-send]");
    if (box && e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (box.value.trim()) box.form.requestSubmit();
    }
  });
  function updateCounts() {
    document.querySelectorAll("[data-count-for]").forEach((out) => {
      const n = document.getElementById(out.dataset.countFor)?.value.length ?? 0;
      out.textContent = `${n} characters${n < 100 ? " — the minimum is usually 100" : ""}`;
    });
  }
  document.addEventListener("input", (e) => { if (e.target.matches?.("[data-count]")) updateCounts(); });
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-copy], [data-copy-from]");
    if (!btn) return;
    const text = btn.dataset.copy ?? document.getElementById(btn.dataset.copyFrom)?.value ?? "";
    navigator.clipboard?.writeText(text).then(() => {
      const label = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => { btn.textContent = label; }, 1500);
    });
  });
  function scrollLog() { const log = document.getElementById("assist-log"); if (log) log.scrollTop = log.scrollHeight; }
  document.addEventListener("click", (e) => {  // "Use this value" buttons fill a form field
    const btn = e.target.closest("[data-fill]");
    const input = btn && document.querySelector(btn.dataset.fill);
    if (input) {
      input.value = btn.dataset.value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
      if (btn.dataset.done) btn.textContent = btn.dataset.done;
    }
    const discard = e.target.closest("[data-discard]");
    if (discard) discard.closest(".ai-draft-item")?.remove();
    const skill = e.target.closest("[data-suggest-skill]");
    if (skill) {
      const group = document.querySelector('.rows[data-group="skills"]');
      const blank = group?.querySelector("[data-row].row-blank");
      const field = blank?.querySelector('[name$="[name]"]');
      if (field && !field.value) {
        field.value = skill.dataset.suggestSkill;
        field.dispatchEvent(new Event("input", { bubbles: true }));
        group.querySelector("[data-add-row]")?.click();
      }
      skill.remove();
    }
  });
  // Inline validation errors come back as 400 with the form re-rendered: swap them in like a 200.
  document.addEventListener("DOMContentLoaded", () => {
    if (window.htmx) {
      htmx.config.responseHandling = [{ code: "204", swap: false }, { code: "[23]..", swap: true },
        { code: "400", swap: true, error: false }, { code: "[45]..", swap: false, error: true }];
    }
  });
  document.addEventListener("DOMContentLoaded", () => { updateCounts(); scrollLog(); });
  document.body.addEventListener("htmx:afterSettle", () => { updateCounts(); scrollLog(); });

  function rowIndex(row) {
    const m = row.querySelector("[name]")?.name.match(/\[(\d+)\]/);
    return m ? Number(m[1]) : 0;
  }

  // Profile editor: reorder rows, keep the posted order, chip inputs, add suggested interests.
  document.addEventListener("click", (e) => {
    const move = e.target.closest("[data-move]");
    if (move) {
      e.preventDefault();  // the buttons sit inside <summary> on project cards
      const row = move.closest("[data-row]");
      const sib = move.dataset.move === "up" ? row.previousElementSibling : row.nextElementSibling;
      if (sib && sib.matches("[data-row]") && !sib.classList.contains("row-blank")) {
        move.dataset.move === "up" ? sib.before(row) : sib.after(row);
        row.closest("form")?.dispatchEvent(new Event("input", { bubbles: true }));
      }
      return;
    }
    if (e.target.closest("summary [data-remove-row]")) e.preventDefault();
    const sug = e.target.closest("[data-suggest]");
    if (sug) {
      const group = document.querySelector('.rows[data-group="boost"]');
      const blank = group?.querySelector("[data-row].row-blank") || group?.querySelector("[data-row]:last-of-type");
      const input = blank?.querySelector('[name$="[keyword]"]');
      if (input && !input.value) {
        input.value = sug.dataset.suggest;
        blank.classList.remove("row-blank");
        input.dispatchEvent(new Event("change", { bubbles: true }));
        group.querySelector("[data-add-row]")?.click();  // keep a fresh blank row at the end
      }
      sug.remove();
    }
  });
  document.addEventListener("submit", (e) => {
    // Rows were moved in the page: renumber group[i] so the server keeps the order you see.
    e.target.querySelectorAll(".rows[data-group]").forEach((group) => {
      const name = group.dataset.group;
      group.querySelectorAll(":scope > [data-row]").forEach((row, i) => {
        row.querySelectorAll("[name]").forEach((el) => {
          el.name = el.name.replace(new RegExp(`^${name}\\[\\d+\\]`), `${name}[${i}]`);
        });
      });
    });
  });
  function chips(input) {
    if (input.dataset.chipsReady) return;
    input.dataset.chipsReady = "1";
    const box = document.createElement("div");
    box.className = "chip-input";
    const entry = document.createElement("input");
    entry.type = "text";
    entry.placeholder = input.placeholder || "Type and press Enter";
    entry.setAttribute("aria-label", input.getAttribute("aria-label") || input.closest("label")?.innerText || "Add");
    const values = () => input.value.split(",").map((s) => s.trim()).filter(Boolean);
    const render = () => {
      box.querySelectorAll(".chip").forEach((c) => c.remove());
      values().forEach((v, i) => {
        const c = document.createElement("span");
        c.className = "chip";
        c.textContent = v + " ";
        const x = document.createElement("button");
        x.type = "button";
        x.textContent = "✕";
        x.setAttribute("aria-label", `Remove ${v}`);
        x.addEventListener("click", () => {
          const vs = values(); vs.splice(i, 1); input.value = vs.join(", "); render();
          input.dispatchEvent(new Event("input", { bubbles: true }));
        });
        c.append(x);
        box.insertBefore(c, entry);
      });
    };
    const add = () => {
      const v = entry.value.replace(/,/g, " ").trim();
      if (v && !values().map((s) => s.toLowerCase()).includes(v.toLowerCase())) {
        input.value = [...values(), v].join(", ");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
      entry.value = ""; render();
    };
    entry.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
      else if (e.key === "Backspace" && !entry.value && values().length) {
        const vs = values(); vs.pop(); input.value = vs.join(", "); render();
      }
    });
    entry.addEventListener("blur", add);
    input.type = "hidden";
    input.after(box);
    box.append(entry);
    box.addEventListener("click", (e) => { if (e.target === box) entry.focus(); });
    render();
  }
  const initChips = (root) => root.querySelectorAll("input[data-chips]").forEach(chips);
  document.addEventListener("DOMContentLoaded", () => initChips(document));
  document.body?.addEventListener("htmx:afterSettle", (e) => initChips(e.target));

  // Enter in a row's first box adds the next row instead of saving the whole profile.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !e.target.matches?.("[data-enter-adds-row]")) return;
    e.preventDefault();
    const group = e.target.closest(".rows");
    const rows = group?.querySelectorAll(":scope > [data-row]");
    if (rows && e.target.closest("[data-row]") === rows[rows.length - 1] && e.target.value.trim()) {
      group.querySelector(":scope > [data-add-row]")?.click();
    } else {
      e.target.closest("[data-row]")?.nextElementSibling?.querySelector("input")?.focus();
    }
  });
  // Phone menu.
  document.addEventListener("click", (e) => {
    const t = e.target.closest(".nav-toggle");
    if (!t) return;
    const open = t.getAttribute("aria-expanded") !== "true";
    t.setAttribute("aria-expanded", String(open));
    document.getElementById(t.getAttribute("aria-controls"))?.classList.toggle("open", open);
  });
  // Filters start folded on phones (they stay open on wider screens).
  document.addEventListener("DOMContentLoaded", () => {
    if (window.matchMedia("(max-width: 640px)").matches) {
      document.querySelectorAll("details.filter-toggle").forEach((d) => {
        if (!d.dataset.active) d.open = false;
      });
    }
  });
  // Unsaved changes: show the save bar, say when saving restarts, warn before leaving.
  const dirtyForms = new Set();
  function markDirty(form, el) {
    if (!form || !form.matches("[data-dirty-guard]")) return;
    dirtyForms.add(form);
    form.classList.add("is-dirty");
    if (el?.matches?.("[data-cold]")) form.dataset.coldChanged = "1";
    const save = form.querySelector("[data-save]");
    if (save && form.dataset.coldChanged) save.textContent = "Save and restart";
  }
  document.addEventListener("input", (e) => markDirty(e.target.closest?.("form"), e.target));
  document.addEventListener("change", (e) => markDirty(e.target.closest?.("form"), e.target));
  document.addEventListener("submit", (e) => { dirtyForms.delete(e.target); });
  window.addEventListener("beforeunload", (e) => {
    if ([...dirtyForms].some((f) => document.body.contains(f))) { e.preventDefault(); e.returnValue = ""; }
  });
})();
