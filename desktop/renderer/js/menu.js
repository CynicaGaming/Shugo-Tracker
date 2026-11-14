// Right-click and dropdown menus: one open at a time, submenus beside their row, an optional × per row.
import { h } from "./dom.js";

let open = [];                       // [top menu, its submenu]

export function closeMenus() {
  open.forEach((m) => m.remove());
  open = [];
}

function place(el, x, y, alignRight, besideOf) {
  document.body.append(el);
  const r = el.getBoundingClientRect(), W = innerWidth, H = innerHeight;
  if (besideOf) {
    const p = besideOf.getBoundingClientRect();
    x = p.right + 2 + r.width > W - 4 ? p.left - r.width - 2 : p.right + 2;
    y = Math.min(p.top - 4, H - r.height - 4);
  } else {
    if (alignRight) x -= r.width;
    if (y + r.height > H - 4) y = Math.max(4, y - r.height);
  }
  el.style.left = `${Math.max(4, Math.min(x, W - r.width - 4))}px`;
  el.style.top = `${Math.max(4, y)}px`;
}

function build(items, level) {
  const el = h("div.menu");
  for (const it of items) {
    if (it === "-") { el.append(h("div.sep")); continue; }
    const off = it.disabled;
    const row = h("div.item", { class: [off && "off", it.selected && "sel"].filter(Boolean).join(" ") },
      it.check !== undefined ? h("span.check", {}, it.check ? "✓" : "") : null,
      h("span.lab", {}, it.label),
      it.submenu ? h("span.arrow", {}, "›") : null,
      it.onRemove ? h("span.x", { title: "", onClick: (e) => { e.stopPropagation(); it.onRemove(); } }, "×") : null);
    if (!off) {
      row.addEventListener("mouseenter", () => {
        el.querySelectorAll(".item.open").forEach((r) => r.classList.remove("open"));
        if (open[level + 1]) { open[level + 1].remove(); open.length = level + 1; }
        if (it.submenu) {
          row.classList.add("open");
          const sub = build(typeof it.submenu === "function" ? it.submenu() : it.submenu, level + 1);
          open[level + 1] = sub;
          place(sub, 0, 0, false, row);
        }
      });
      if (!it.submenu) row.addEventListener("click", () => { closeMenus(); it.onClick?.(); });
    }
    el.append(row);
  }
  el.addEventListener("mousedown", (e) => e.stopPropagation());
  el.addEventListener("contextmenu", (e) => e.preventDefault());
  return el;
}

/** Show a menu at (x, y). items: {label, onClick, disabled, selected, check, submenu, onRemove} or "-". */
export function showMenu(items, x, y, { alignRight = false } = {}) {
  closeMenus();
  const el = build(items, 0);
  open = [el];
  place(el, x, y, alignRight);
  return el;
}

/** Redraw an open submenu after its items changed (e.g. a row removed with ×). */
export function refreshOpenSub(items) {
  const sub = open[1];
  if (!sub) return;
  if (!items.length) { closeMenus(); return; }
  const anchor = open[0].querySelector(".item.open");
  const fresh = build(items, 1);
  sub.replaceWith(fresh);
  open[1] = fresh;
  if (anchor) place(fresh, 0, 0, false, anchor);
}

// a click anywhere else, Esc, or the window losing focus closes the menu
addEventListener("mousedown", () => closeMenus());
addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });
addEventListener("blur", () => closeMenus());
addEventListener("resize", () => closeMenus());
