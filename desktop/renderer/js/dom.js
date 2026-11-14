// Small DOM helpers, icons and the colour tables shared by every view.

export function h(tag, attrs, ...kids) {
  const [name, ...classes] = tag.split(".");
  const el = name === "svg" || name === "path" ? document.createElementNS("http://www.w3.org/2000/svg", name)
    : document.createElement(name || "div");
  if (classes.length) el.setAttribute("class", classes.join(" "));
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "style" && typeof v === "object") {
      for (const [p, val] of Object.entries(v)) {
        if (p.startsWith("--")) el.style.setProperty(p, val);       // custom properties (grade colours)
        else el.style[p] = val;
      }
    }
    else if (k === "class") el.setAttribute("class", [el.getAttribute("class"), v].filter(Boolean).join(" "));
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}

export const clear = (el) => { while (el.firstChild) el.firstChild.remove(); return el; };
export const fmtInt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-US"));
export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const REGION_NAMES = { nae: "NA - East", naw: "NA - West", eu: "Europe", la: "Latin America", as: "Asia" };
export const CLASSES = ["Gladiator", "Templar", "Ranger", "Assassin", "Spiritmaster", "Sorcerer", "Cleric", "Chanter", "Brawler"];
export const CLASS_COLORS = {
  Gladiator: "#e0864a", Templar: "#d8b44a", Ranger: "#7fc06a", Assassin: "#c96ad6", Spiritmaster: "#5fc4c4",
  Sorcerer: "#6a8fe0", Cleric: "#f0e08a", Chanter: "#8ad49a", Brawler: "#e06a6a",
};
export const GRADE_COLORS = {
  Common: "#b8bcc6", Rare: "#6fd38a", Legend: "#5aa9ff", Unique: "#e2b84a", Epic: "#ff8a3d", Special: "#4fd1c5",
  Mythic: "#ff5c8a",
};
export const gradeColor = (g) => GRADE_COLORS[g] || "#b8bcc6";
export const factionColor = (race) => (race === 1 ? "var(--elyos)" : race === 2 ? "var(--asmo)" : "var(--faint)");

const P = (d, extra = "") => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ${extra}>${d}</svg>`;
export const ICONS = {
  search: P('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
  close: P('<path d="M6 6l12 12M18 6 6 18"/>'),
  min: P('<path d="M6 12h12"/>'),
  pin: P('<path d="M9 4h6l-1 5 3 3v2H7v-2l3-3z"/><path d="M12 14v6"/>'),
  person: P('<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>'),
  back: P('<path d="M15 18l-6-6 6-6"/>'),
  star: P('<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>'),
  starFill: P('<path fill="currentColor" d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>'),
  refresh: P('<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>'),
  cog: P('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  update: P('<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/>'),
  grip: P('<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>'),
  caret: P('<path d="m6 9 6 6 6-6"/>'),
  swords: P('<path d="M14.5 17.5 3 6V3h3l11.5 11.5"/><path d="m13 19 6-6"/><path d="m16 16 4 4"/><path d="M19 21l2-2"/>'),
};
export const icon = (name) => h("span", { html: ICONS[name], style: { display: "contents" } });

export const LOGO = `<svg viewBox="0 0 32 32"><defs><linearGradient id="lg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f6d27a"/><stop offset="1" stop-color="#c8922e"/></linearGradient></defs><rect x="1" y="1" width="30" height="30" rx="7" fill="#141a26" stroke="url(#lg)" stroke-width="1.5"/><path d="M18 4 9 18h6l-2 10 10-15h-6z" fill="url(#lg)"/></svg>`;

/** Lay out the table columns for a list `width` px wide (mirrors shugotracker/columns.py). */
const SPEC = [["name", 130, 1e6, 3, "w", 0], ["legion", 56, 170, 2, "w", 2], ["class", 70, 112, 1, "w", 3],
  ["level", 24, 24, 0, "e", 0], ["server", 90, 200, 2, "w", 1], ["gs", 44, 52, 0, "e", 0], ["cp", 60, 72, 0, "e", 0],
  ["seen", 64, 96, 0, "w", 2]];
export const COL_LABELS = { name: "Name", legion: "Legion", class: "Class", level: "Lv", server: "Server", gs: "GS", cp: "CP", seen: "Last seen" };
export const COL_MENU = { ...COL_LABELS, level: "Level", gs: "Gear score", cp: "Combat power" };
export const DEFAULT_COLUMNS = ["legion", "class", "level", "server", "gs", "cp", "seen"];
export function layoutColumns(width, keys) {
  const GAP = 10, STAR = 24, x1 = width - 6, left = 8, right = x1 - STAR, avail = right - left;
  const byKey = Object.fromEntries(SPEC.map((c) => [c[0], c]));
  let cols = [byKey.name, ...keys.filter((k) => byKey[k] && k !== "name").map((k) => byKey[k])];
  const need = (cs) => cs.reduce((a, c) => a + c[1], 0) + GAP * (cs.length - 1);
  for (const drop of [1, 2, 3]) { if (need(cols) <= avail) break; cols = cols.filter((c) => c[5] !== drop); }
  const w = Object.fromEntries(cols.map((c) => [c[0], c[1]]));
  let spare = avail - need(cols);
  if (spare < 0) w.name = Math.max(40, w.name + spare);
  while (spare > 0.5) {
    const flex = cols.filter((c) => c[3] && w[c[0]] < c[2]);
    if (!flex.length) break;
    const total = flex.reduce((a, c) => a + c[3], 0);
    let used = 0;
    for (const c of flex) { const add = Math.min(spare * c[3] / total, c[2] - w[c[0]]); w[c[0]] += add; used += add; }
    spare -= used;
    if (used < 0.5) break;
  }
  const spans = {}; let x = left;
  for (const c of cols) { spans[c[0]] = [Math.round(x), Math.round(x + w[c[0]]), c[4]]; x += w[c[0]] + GAP; }
  return { x1, star: x1 - 11, spans };
}

/** Sort rows like shugotracker/sorting.py: numbers biggest first, text A–Z, empty last; sides kept grouped. */
const SORTS = {
  name: [(c) => c.name.toLowerCase(), false], legion: [(c) => (c.legion || "").toLowerCase() || null, false],
  class: [(c) => (c.class_name || "").toLowerCase() || null, false], level: [(c) => c.level || null, true],
  server: [(c) => (c.server_name ? `${c.region}|${c.server_name.toLowerCase()}` : null), false],
  gs: [(c) => c.gear_score, true], cp: [(c) => c.combat_power, true],
};
export function sortChars(chars, key, reverse, sideOf, when) {
  let out = [...chars];
  let val = null, desc = false;
  if ((key === "latest" || key === "seen") && when) { val = (c) => when[c.key] ?? when[c.name] ?? null; desc = true; }
  else if (SORTS[key]) [val, desc] = SORTS[key];
  if (val) {
    const known = out.filter((c) => val(c) != null), unknown = out.filter((c) => val(c) == null);
    const dir = (desc !== !!reverse) ? -1 : 1;
    known.sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * dir; });
    out = known.concat(unknown);
  }
  if (sideOf) { const order = { enemy: 0, ally: 1 }; out = out.map((c, i) => [c, i]).sort((a, b) =>
    ((order[sideOf[a[0].name]] ?? 2) - (order[sideOf[b[0].name]] ?? 2)) || a[1] - b[1]).map((p) => p[0]); }
  return out;
}

export function ago(t) {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
