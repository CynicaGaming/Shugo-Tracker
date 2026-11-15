// The window: title bar, Search / Favorites / Nearby / Recent lists, menus, footer. Profile and Settings open
// in place of the list (profile.js, settings.js).
import { call, on, win } from "./bridge.js";
import { CLASSES, CLASS_COLORS, COL_LABELS, COL_MENU, DEFAULT_COLUMNS, ICONS, LOGO, REGION_NAMES, ago, clear,
  factionColor, fmtInt, h, icon, layoutColumns, sortChars } from "./dom.js";
import { closeMenus, refreshOpenSub, showMenu } from "./menu.js";
import { ProfileView } from "./profile.js";
import { SettingsView } from "./settings.js";
import { FinderView } from "./finder.js";

const ROW = 38;
const S = {                                    // everything the window shows
  cfg: {}, version: "", demo: false, regions: [],
  mode: "search", screen: "list",              // screen: list | profile | settings | finder
  keyword: "", gen: 0, results: [], regionState: {},
  chars: new Map(), favorites: [], my: { slots: [], active: null },
  nearby: { enabled: false, state: "", rows: [], recent: [] },
  update: { state: "idle" },                   // the self-updater (desktop/updater.js)
};
export const app = { S, call, save, openProfile, closeScreen, myChar, pickMine, refreshList: () => list.render() };

function save(key, value) { S.cfg[key] = value; call("config.set", { key, value }); }
const fset = (key) => new Set(S.cfg[key] || []);

/* ═════ title bar ═════ */
const root = document.getElementById("app");
const titlebar = h("div.titlebar");
const view = h("div.view");
const footer = h("div.footer");
root.append(titlebar, view, footer);

let titleSig = "";
function paintTitlebar() {
  // Redrawn on many events (Nearby, cards, updates): only when something it shows has changed.
  const me0 = myChar(), up0 = S.update;
  const sig = JSON.stringify([S.screen, S.mode, S.favorites.length, S.nearby.enabled, S.nearby.rows.length,
    S.nearby.recent.length, up0.state, up0.latest, Math.round((up0.progress || 0) * 100), up0.clicked,
    S.cfg.always_on_top, me0?.key, me0?.portrait, me0?.name, me0?.server_name, S.my.slots.some(Boolean)]);
  if (sig === titleSig) return;
  titleSig = sig;
  clear(titlebar);
  titlebar.append(h("span.logo", { html: LOGO }));
  const tabs = h("div.tabs");
  if (S.screen !== "list") {
    const back = { profile: { search: "Search", favorites: "Favorites", nearby: "Nearby", recent: "Recent" }[S.mode], settings: "Back", finder: S.my.slots.some(Boolean) ? "Back" : "Skip" }[S.screen];
    tabs.append(h("button.tab.back", { onClick: closeScreen }, icon("back"), back));
  } else {
    const t = (mode, label, count) => h("button.tab", { class: S.mode === mode ? "on" : "", onClick: () => setMode(mode) },
      label, count ? h("span.count", {}, count) : null);
    tabs.append(t("search", "Search"), t("favorites", "Favorites", S.favorites.length || ""));
    if (S.nearby.enabled) tabs.append(t("nearby", "Nearby", S.nearby.rows.length || ""), t("recent", "Recent", S.nearby.recent.length || ""));
    else tabs.append(t("nearby", "Nearby"));
  }
  titlebar.append(tabs, h("span.grow"));
  const pinned = S.cfg.always_on_top !== false;
  titlebar.append(h("button.iconbtn", { class: pinned ? "on" : "", html: ICONS.pin, title: "",
    onClick: () => { save("always_on_top", !pinned); win.setAlwaysOnTop(!pinned); paintTitlebar(); } }));
  const me = myChar();
  // An update shows as a dot on your picture; the menu holds the button (and Settings → Updates the details).
  const up = updateItem();
  const meBtn = h("button.mebtn", { onClick: (e) => { e.stopPropagation(); meMenu(meBtn); },
    onMousedown: (e) => e.stopPropagation() },
    h("span.pic", {},
      me?.portrait ? h("img", { src: me.portrait }) : h("span.ph", { html: ICONS.person, style: { color: "var(--dim)", padding: "3px" } }),
      up ? h("i.udot", { class: up.kind }) : null),
    me ? h("span.nm", {}, `${me.name} · ${me.server_name}`) : null);
  titlebar.append(meBtn,
    h("button.iconbtn", { html: ICONS.min, onClick: () => win.minimize() }),
    h("button.iconbtn.close", { html: ICONS.close, onClick: () => win.close() }));
}

function myChar() {
  const d = S.my.active != null ? S.my.slots[S.my.active] : null;
  if (!d) return null;
  return S.chars.get(`${d.server_id}:${d.char_id}`) || { ...d, key: `${d.server_id}:${d.char_id}` };
}

function meMenu(anchor) {
  const r = anchor.getBoundingClientRect();
  const me = myChar();
  const used = S.my.slots.map((d, i) => [i, d]).filter(([, d]) => d);
  const switchItems = () => S.my.slots.map((d, i) => [i, d]).filter(([, d]) => d).map(([i, d]) => ({
    label: `${i + 1}.  ${d.name}${d.server_name ? " · " + d.server_name : ""}`, selected: i === S.my.active,
    onClick: () => setMy("my.switch", { slot: i }),
    onRemove: async () => { await setMy("my.delete", { slot: i }); refreshOpenSub(switchItems()); },
  }));
  const items = [];
  const up = updateItem();
  if (up) items.push({ label: up.label, disabled: up.kind === "busy", onClick: updateClick }, "-");
  if (me) items.push({ label: "My profile", onClick: async () => openProfile(await call("my.character")) });
  if (used.length) items.push({ label: "Switch Profile", submenu: switchItems });
  const free = S.my.slots.findIndex((d) => !d);
  if (free >= 0) items.push({ label: used.length ? "Add character" : "Find my character", onClick: () => openFinder(free) });
  items.push("-", { label: "Settings", onClick: openSettings });
  showMenu(items, r.right, r.bottom + 2, { alignRight: true });
}

async function setMy(method, params) {
  S.my = await call(method, params);
  paintTitlebar();
  profile?.myChanged();
}

/** The update step to offer, if any: Download, Installing… (busy), Restart, or Retry after a failed click. */
function updateItem() {
  const u = S.update;
  if (u.state === "available") return { kind: "new", label: `Download v${u.latest}` };
  if (u.state === "downloading") return { kind: "busy", label: `Installing v${u.latest}… ${Math.round((u.progress || 0) * 100)}%` };
  if (u.state === "ready") return { kind: "new", label: `Restart for v${u.latest}` };
  if (u.state === "error" && u.clicked) return { kind: "bad", label: "Update failed · Retry" };
  return null;
}

/** One button for every step: download when available, restart when downloaded, retry after an error. */
async function updateClick() {
  S.update.clicked = true;
  const st = S.update.state;
  if (st === "available" || st === "error") S.update = { ...(await win.update(st === "error" ? "check" : "download")), clicked: true };
  else if (st === "ready") await win.update("restart");
  paintTitlebar();
}
app.updateClick = updateClick;
win.onUpdate((s) => { S.update = { ...s, clicked: S.update.clicked }; paintTitlebar(); settings?.paintUpdate?.(); });

/* ═════ modes, filters ═════ */
function setMode(mode) {
  if (mode === "nearby" && !S.nearby.enabled) { S.mode = mode; S.screen = "list"; render(); return; }
  S.mode = mode;
  render();
}

function closeScreen() {
  if (S.screen === "finder" && !S.cfg.setup_done) save("setup_done", true);   // skipped: don't ask again
  profile?.destroy(); profile = null; settings = null; finder = null;
  S.screen = "list";
  render();
}

let profile = null, settings = null, finder = null;
function openFinder(slot) {
  closeMenus();
  S.screen = "finder";
  finder = new FinderView(app, slot);
  render();
}
/** Found yourself: save the character in the given (or first free) slot, make it active, back to the list. */
async function pickMine(c, slot) {
  const free = S.my.slots.findIndex((d) => !d);
  const i = slot ?? (free >= 0 ? free : 0);
  await setMy("my.set", { key: c.key, slot: i });
  if (S.my.active !== i) await setMy("my.switch", { slot: i });
  closeScreen();
}
function openProfile(c) {
  if (!c) return;
  closeMenus();
  profile?.destroy();
  S.screen = "profile";
  profile = new ProfileView(app, c);
  render();
}
function openSettings() {
  S.screen = "settings";
  settings = new SettingsView(app);
  render();
}

const searchInput = h("input", { placeholder: "Search a character name", spellcheck: "false",
  onInput: () => { clearTimeout(searchInput._t); if (searchInput.value.trim().length >= 2) searchInput._t = setTimeout(() => runSearch(searchInput.value.trim()), 350); },
  onKeydown: (e) => { if (e.key === "Enter") runSearch(searchInput.value.trim(), true); } });

function serverFilters() {
  return { classes: S.cfg.classes || [], factions: S.cfg.factions || [], level_min: S.cfg.level_min ?? null, level_max: S.cfg.level_max ?? null };
}

async function runSearch(kw, force = false) {
  if (!kw || (kw === S.keyword && !force && JSON.stringify(serverFilters()) === S.searchedFilters)) return;
  S.keyword = kw;
  S.searchedFilters = JSON.stringify(serverFilters());
  S.results = [];
  S.regionState = Object.fromEntries(S.regions.map((r) => [r, { page: 0, total: null, loading: true, error: null }]));
  if (S.mode !== "search") S.mode = "search";
  if (S.screen !== "list") closeScreen();
  list.scrollTop(0);
  S.gen += 1;                                     // set first: cached pages can arrive before the reply
  render();
  call("search", { keyword: kw, filters: serverFilters(), gen: S.gen });
}

on("search", (d) => {
  if (d.gen !== S.gen) return;
  const st = S.regionState[d.region];
  if (!st) return;
  st.loading = false; st.error = d.error;
  if (d.error) { list.render(); return; }
  st.page = d.page; st.total = d.total;
  const seen = new Set(S.results.map((c) => c.key));
  for (const c of d.chars) { S.chars.set(c.key, c); if (!seen.has(c.key)) S.results.push(c); }
  if (d.page === 1) S.results = rankKeyword(S.results, S.keyword);
  list.render(); paintFooter();
});

function rankKeyword(chars, kw) {
  const k = kw.toLowerCase();
  const score = (c) => { const n = c.name.toLowerCase(); return n === k ? 0 : n.startsWith(k) ? 1 : 2; };
  return chars.map((c, i) => [c, i]).sort((a, b) => score(a[0]) - score(b[0]) || a[1] - b[1]).map((p) => p[0]);
}

on("card", (c) => {
  const old = S.chars.get(c.key);
  if (old) Object.assign(old, c); else S.chars.set(c.key, c);
  for (const arr of [S.results, S.favorites]) {
    const i = arr.findIndex((x) => x.key === c.key);
    if (i >= 0 && arr[i] !== old) Object.assign(arr[i], c);
  }
  list.renderSoon();
  if (myChar()?.key === c.key) paintTitlebar();
});

let askedAdmin = false;
on("nearby", (d) => {
  const toggled = d.enabled !== S.nearby.enabled;
  S.nearby = d;
  // Nearby is on but this copy isn't administrator (a normal start): restart as administrator once, like
  // turning it on does. Declined: the Nearby tab offers the button.
  if (d.enabled && d.state === "no_admin" && !askedAdmin && !S.demo) { askedAdmin = true; win.relaunchAsAdmin(); }
  if (toggled && S.screen === "list") { render(); return; }      // filters and headers come and go with it
  for (const r of [...d.rows, ...d.recent]) S.chars.set(r.char.key, r.char);
  if (S.screen === "list") paintTitlebar();
  if (S.mode === "nearby" || S.mode === "recent") { list.render(); paintFooter(); }
});

function filtersBar() {
  const box = h("div.filters");
  const regions = fset("regions"), factions = fset("factions"), classes = fset("classes");
  const toggle = (key, value) => {
    const s = fset(key);
    s.has(value) ? s.delete(value) : s.add(value);
    save(key, [...s]);
    filtersChanged();
  };
  // Region: one segmented control; none picked means every region.
  const seg = h("div.seg");
  for (const r of S.regions) seg.append(h("button", { class: regions.has(r) ? "on" : "", onClick: () => toggle("regions", r) }, REGION_NAMES[r] || r));
  box.append(seg);

  // Faction toggles, the Filters panel (class and level), and Reset when anything is set.
  const levelSet = S.cfg.level_min != null || S.cfg.level_max != null;
  const extra = classes.size + (levelSet ? 1 : 0);
  const open = !!S.cfg.filters_open;
  const row = h("div.frow2");
  for (const [v, n] of [["1", "Elyos"], ["2", "Asmodians"]]) {
    row.append(h("button.pill", { class: factions.has(v) ? "on" : "", style: { "--fc": factionColor(+v) }, onClick: () => toggle("factions", v) },
      h("i.dia"), n));
  }
  row.append(h("span.grow"));
  if (regions.size || factions.size || extra) row.append(h("button.link", { onClick: () => {
    for (const k of ["regions", "factions", "classes"]) S.cfg[k] = [];
    S.cfg.level_min = S.cfg.level_max = null;
    for (const k of ["regions", "factions", "classes", "level_min", "level_max"]) call("config.set", { key: k, value: S.cfg[k] });
    filtersChanged(); } }, "Reset"));
  row.append(h("button.pill.more", { class: open ? "open" : extra ? "on" : "", onClick: () => { save("filters_open", !open); render(); } },
    icon("sliders"), "Filters", extra ? h("b.count", {}, String(extra)) : null));
  box.append(row);

  if (open) {
    const panel = h("div.fpanel");
    const cls = h("div.fclasses");
    for (const c of CLASSES) {
      cls.append(h("button.pill", { class: classes.has(c) ? "on" : "", style: { "--fc": CLASS_COLORS[c] }, onClick: () => toggle("classes", c) }, h("i.dot"), c));
    }
    const lv = (key) => h("input.lvl", { value: S.cfg[key] ?? "", placeholder: key === "level_min" ? "1" : "45", inputmode: "numeric",
      onInput: (e) => { clearTimeout(e.target._t); e.target._t = setTimeout(() => {
        const n = parseInt(e.target.value, 10); save(key, Number.isFinite(n) ? Math.max(1, Math.min(45, n)) : null); filtersChanged(false);
      }, 600); } });
    panel.append(h("div.flabel", {}, "Class"), cls,
      h("div.flabel", {}, "Level"), h("div.flevel", {}, lv("level_min"), h("span", {}, "to"), lv("level_max")));
    box.append(panel);
  }
  return box;
}

function filtersChanged(repaint = true) {
  if (repaint) render(); else { list.render(); paintFooter(); }
  if (S.mode === "search" && S.keyword && JSON.stringify(serverFilters()) !== S.searchedFilters) runSearch(S.keyword, true);
}

/* ═════ the list ═════ */
function source() {
  if (S.mode === "nearby") return S.nearby.enabled ? S.nearby.rows.map((r) => r.char) : [];
  if (S.mode === "recent") return S.nearby.enabled ? S.nearby.recent.map((r) => r.char) : [];
  return S.mode === "favorites" ? S.favorites : S.results;
}

function visible() {
  let out = source().map((c) => S.chars.get(c.key) || c);
  const regions = fset("regions"), factions = fset("factions"), classes = fset("classes");
  if (regions.size) out = out.filter((c) => regions.has(c.region));
  if (factions.size) out = out.filter((c) => factions.has(String(c.race)));
  if (classes.size) out = out.filter((c) => classes.has(c.class_name));
  if (S.cfg.level_min != null) out = out.filter((c) => c.level >= S.cfg.level_min);
  if (S.cfg.level_max != null) out = out.filter((c) => c.level <= S.cfg.level_max);
  const [key, rev] = (S.cfg.sorts || {})[S.mode] || ["default", false];
  const grouped = S.mode === "nearby" || S.mode === "recent";
  const sideOf = grouped ? Object.fromEntries((S.mode === "recent" ? S.nearby.recent : S.nearby.rows).map((r) => [r.char.name, r.side])) : null;
  const when = S.mode === "recent" ? Object.fromEntries(S.nearby.recent.map((r) => [r.char.key, r.seen])) : null;
  return sortChars(out, key, rev, sideOf, when);
}

function columns() {
  const cols = (S.cfg.columns || DEFAULT_COLUMNS).filter((k) => COL_LABELS[k]);
  return S.mode === "recent" ? cols : cols.filter((k) => k !== "seen");
}

const list = (() => {
  const head = h("div.thead");
  const box = h("div.list");
  const spacer = h("div.spacer");
  box.append(spacer);
  let rows = [], layout = null, layoutSig = "", frame = 0, drawFrame = 0, wantTimer = 0;
  // Row elements are kept by character and reused while what they show is unchanged, so scrolling and card
  // updates only build the rows that are new or different (and portraits never reload).
  const made = new Map();                                // key -> { el, sig }
  box.addEventListener("scroll", () => { cancelAnimationFrame(drawFrame); drawFrame = requestAnimationFrame(draw); }, { passive: true });
  new ResizeObserver(() => render()).observe(box);

  function render() {
    rows = visible();
    layout = layoutColumns(box.clientWidth || 560, columns());
    const sig = JSON.stringify(layout) + S.mode;
    if (sig !== layoutSig) { layoutSig = sig; made.clear(); }
    drawHead();
    draw();
  }
  function renderSoon() { cancelAnimationFrame(frame); frame = requestAnimationFrame(render); }

  function drawHead() {
    clear(head);
    const [key, rev] = (S.cfg.sorts || {})[S.mode] || ["default", false];
    for (const [k, [x0, x1, anchor]] of Object.entries(layout.spans)) {
      const sorted = key === k;
      const natural = ["level", "gs", "cp"].includes(k);
      head.append(h("div.col", { class: sorted ? "sorted" : "", "data-arrow": (natural !== !!rev) ? "▼" : "▲",
        style: { left: `${x0}px`, width: `${x1 - x0}px`, justifyContent: anchor === "e" ? "flex-end" : "flex-start" },
        onClick: () => setSort(k) }, COL_LABELS[k]));
    }
    head.oncontextmenu = (e) => { e.preventDefault(); columnsMenu(e.clientX, e.clientY); };
  }

  function draw() {
    const top = box.scrollTop, height = box.clientHeight;
    const grouped = S.mode === "nearby" || S.mode === "recent";
    // everything rows need, worked out once per draw
    const ctx = {
      fav: new Set(S.favorites.map((f) => f.key)),
      side: grouped ? new Map((S.mode === "recent" ? S.nearby.recent : S.nearby.rows).map((r) => [r.char.name, r.side])) : new Map(),
      recent: S.mode === "recent" ? new Map(S.nearby.recent.map((r) => [r.char.key, r])) : null,
      here: S.mode === "recent" ? new Set(S.nearby.rows.map((r) => r.char.key)) : null,
      race: grouped ? { enemy: sideRace("enemy"), ally: sideRace("ally") } : {},
    };
    const items = [];                                     // [y, kind, payload]
    let y = 0, lastSide = null;
    for (const c of rows) {
      const side = ctx.side.get(c.name);
      if (grouped && side && side !== lastSide) { items.push([y, "group", side]); y += 28; lastSide = side; }
      items.push([y, "row", c]); y += ROW;
    }
    const wanted = fset("regions");
    const loading = S.mode === "search" && Object.entries(S.regionState).some(([r, st]) => st.loading && (!wanted.size || wanted.has(r)));
    for (let i = 0; loading && i < 6; i++) { items.push([y, "skel"]); y += ROW; }
    spacer.style.height = `${y}px`;
    const nodes = [], want = [], shown = new Set();
    for (const [iy, kind, p] of items) {
      if (iy + ROW < top - 200 || iy > top + height + 200) continue;
      if (kind === "group") {
        const race = ctx.race[p];
        nodes.push(h("div.group", { class: p, style: { top: `${iy + 2}px`, ...(race ? { color: factionColor(race) } : {}) } },
          race === 1 ? "Elyos" : race === 2 ? "Asmodians" : p === "enemy" ? "Enemies" : "Allies"));
      } else if (kind === "skel") nodes.push(skeletonRow(iy));
      else {
        nodes.push(rowFor(p, iy, ctx)); shown.add(p.key);
        if (p.status === "none" || !p.status || p.stale) want.push(p.key);
      }
    }
    if (!items.length && !loading) nodes.push(emptyState());
    spacer.replaceChildren(...nodes);
    if (made.size > 400) for (const k of made.keys()) if (!shown.has(k)) made.delete(k);
    if (want.length) { clearTimeout(wantTimer); wantTimer = setTimeout(() => call("cards.want", { keys: want }), 30); }
    if (S.mode === "search" && top + height > y - ROW * 8) loadMore();
  }

  /** A row for c at height y: the one already made if nothing it shows has changed, else a new one. */
  function rowFor(c, y, ctx) {
    const side = ctx.side.get(c.name), r = ctx.recent?.get(c.key), here = ctx.here?.has(c.key);
    const sig = [c.name, c.class_name, c.level, c.legion, c.server_name, c.region, c.race, c.portrait, c.status,
      c.gear_score, c.combat_power, ctx.fav.has(c.key), side, ctx.race[side], r && ago(r.seen), r?.fought, here].join("|");
    let m = made.get(c.key);
    if (!m || m.sig !== sig) { m = { el: rowEl(c, side, ctx, r, here), sig }; made.set(c.key, m); }
    m.el.style.top = `${y}px`;
    return m.el;
  }

  function cell(k, c, r, here) {
    const [x0, x1, anchor] = layout.spans[k];
    const style = { left: `${x0}px`, width: `${x1 - x0}px`, justifyContent: anchor === "e" ? "flex-end" : "flex-start" };
    const loading = c.status === "loading" || c.status === "none" || !c.status;
    const num = (v, cls = "") => h("div.c.num", { class: cls, style }, loading && v == null ? h("i.ph") : fmtInt(v));
    switch (k) {
      case "name": {
        const col = CLASS_COLORS[c.class_name] || "var(--dim)";
        return h("div.c.name", { style },
          S.mode === "favorites" ? h("span.grip", { html: ICONS.grip, onMousedown: (e) => startDrag(e, c) }) : null,
          h("span.badge", { style: { color: col, boxShadow: `inset 0 0 0 1px ${col}33` } },
            c.portrait ? h("img", { src: c.portrait, loading: "lazy", onError: (e) => e.target.replaceWith((c.class_name || "?")[0]) })
              : (c.class_name || "?")[0]),
          h("span", {}, c.name), h("span.faction", { style: { background: factionColor(c.race) } }));
      }
      case "legion": return h("div.c.dim", { style }, h("span", {}, c.legion || ""));
      case "class": return h("div.c", { style: { ...style, color: CLASS_COLORS[c.class_name] || "var(--dim)" } }, h("span", {}, c.class_name || ""));
      case "level": return h("div.c.num", { style }, c.level || "");
      case "server": return h("div.c.dim", { style }, h("span", {}, `${c.server_name} · ${REGION_NAMES[c.region] || c.region}`));
      case "gs": return num(c.gear_score);
      case "cp": return num(c.combat_power, "cp");
      case "seen":
        return h("div.c", { style: { ...style, color: here ? "var(--green)" : "var(--dim)" } },
          r?.fought ? h("span.fought", {}, "⚔") : null, h("span", {}, here ? "Here now" : r ? ago(r.seen) : ""));
    }
    return null;
  }

  function rowEl(c, side, ctx, r, here) {
    const fav = ctx.fav.has(c.key);
    const el = h("div.row", {
      onClick: (e) => { if (!e.target.closest(".star") && !e.target.closest(".grip")) openProfile(c); },
      onContextmenu: (e) => { e.preventDefault(); rowMenu(c, e.clientX, e.clientY); } });
    if (side) { const race = ctx.race[side]; el.append(h("span.side", { style: { background: race ? factionColor(race) : side === "enemy" ? "#ff6b6b" : "#6ab8ff" } })); }
    for (const k of Object.keys(layout.spans)) el.append(cell(k, c, r, here));
    el.append(h("div.c.star", { class: fav ? "on" : "", style: { left: `${layout.star - 10}px`, width: "20px" },
      html: fav ? ICONS.starFill : ICONS.star, onClick: () => toggleFavorite(c) }));
    return el;
  }

  function skeletonRow(y) {
    const el = h("div.row.skeleton", { style: { top: `${y}px` } });
    for (const [k, [x0, x1]] of Object.entries(layout.spans)) {
      el.append(h("div.c", { style: { left: `${x0}px`, width: `${x1 - x0}px` } }, h("i", { style: { width: k === "name" ? "60%" : "70%" } })));
    }
    return el;
  }

  /** Which faction a Nearby side is (enemies are listed first): from the players on it, else from your
   *  character's faction. 0 when nobody's faction is known yet. */
  function sideRace(side) {
    if (side !== "enemy" && side !== "ally") return 0;
    for (const r of [...S.nearby.rows, ...S.nearby.recent]) {
      const race = r.char?.race;
      if ((race === 1 || race === 2) && (r.side === "enemy" || r.side === "ally")) return r.side === side ? race : 3 - race;
    }
    const me = myChar();
    if (me?.race === 1 || me?.race === 2) return side === "ally" ? me.race : 3 - me.race;
    return 0;
  }

  function emptyState() {
    let [t, sub] = ["", ""];
    if (S.mode === "search") [t, sub] = S.keyword ? ["No results", "Try another name or fewer filters"] : ["Search for a character", ""];
    else if (S.mode === "favorites") [t, sub] = ["No favorites yet", ""];
    else if (!S.nearby.enabled) return nearbyOptIn();
    else if (S.mode === "recent") t = S.nearby.recent.length ? "No results" : "No recent players";
    else if (S.nearby.state === "no_admin") {
      return h("div.empty", { style: { position: "absolute", left: 0, right: 0, top: "40px" } }, h("div", {},
        h("b", {}, "Nearby needs administrator"),
        h("div", { style: { margin: "0 auto 14px" } }, "Windows only lets administrators read the game's traffic."),
        h("button.btn.gold", { onClick: () => win.relaunchAsAdmin() }, "Restart as administrator")));
    }
    else t = { waiting: "Waiting for AION 2", starting: "Starting…", error: "Nearby stopped", capturing: S.nearby.rows.length ? "No results" : "No players nearby" }[S.nearby.state] || "";
    if (S.nearby.state === "error" && S.mode === "nearby") sub = S.nearby.detail || "";
    return h("div.empty", { style: { position: "absolute", left: 0, right: 0, top: "40px" } }, h("div", {}, h("b", {}, t), sub));
  }

  function nearbyOptIn() {
    return h("div.empty", { style: { position: "absolute", left: 0, right: 0, top: "30px" } }, h("div", {},
      h("b", {}, "Nearby"),
      h("div", { style: { maxWidth: "330px", margin: "0 auto 14px" } }, "The players around your character, with their combat power and gear score."),
      h("button.btn.gold", { onClick: async () => { S.nearby = await call("nearby.enable", { on: true }); if (S.nearby.state === "no_admin") win.relaunchAsAdmin(); app.render(); } }, "Turn on Nearby")));
  }

  let drag = null;
  function startDrag(e, c) {
    e.preventDefault(); e.stopPropagation();
    drag = { key: c.key, startY: e.clientY, from: S.favorites.findIndex((f) => f.key === c.key) };
    const move = (ev) => {
      const dy = ev.clientY - drag.startY;
      drag.to = Math.max(0, Math.min(S.favorites.length - 1, drag.from + Math.round(dy / ROW)));
      const order = [...S.favorites];
      const [it] = order.splice(drag.from, 1); order.splice(drag.to, 0, it);
      rows = order; draw();
    };
    const up = async () => {
      removeEventListener("mousemove", move); removeEventListener("mouseup", up);
      if (drag.to != null && drag.to !== drag.from) S.favorites = await call("favorites.move", { key: drag.key, index: drag.to });
      drag = null; render();
    };
    addEventListener("mousemove", move); addEventListener("mouseup", up);
  }

  return { head, box, render, renderSoon, scrollTop: (y) => { box.scrollTop = y; }, get count() { return rows.length; } };
})();

function loadMore() {
  const wanted = fset("regions");
  for (const [r, st] of Object.entries(S.regionState)) {
    if ((wanted.size && !wanted.has(r)) || st.loading || st.error || st.total == null || st.page * 50 >= st.total) continue;
    st.loading = true;
    call("search.more", { gen: S.gen, keyword: S.keyword, region: r, page: st.page + 1, filters: serverFilters() });
  }
}

function setSort(k) {
  const sorts = { ...(S.cfg.sorts || {}) };
  const [key, rev] = sorts[S.mode] || ["default", false];
  sorts[S.mode] = key !== k ? [k, false] : rev ? ["default", false] : [k, true];
  save("sorts", sorts);
  list.render();
}

function columnsMenu(x, y) {
  const cols = S.cfg.columns || DEFAULT_COLUMNS;
  const items = DEFAULT_COLUMNS.map((k) => ({ label: COL_MENU[k] + (k === "seen" ? "  (Recent)" : ""), check: cols.includes(k),
    onClick: () => { save("columns", cols.includes(k) ? cols.filter((c) => c !== k) : DEFAULT_COLUMNS.filter((c) => c === k || cols.includes(c))); list.render(); } }));
  items.push("-", { label: "Reset columns", onClick: () => { save("columns", [...DEFAULT_COLUMNS]); list.render(); } });
  showMenu(items, x, y);
}

async function toggleFavorite(c) {
  const r = await call("favorites.toggle", { key: c.key });
  S.favorites = r.favorites;
  paintTitlebar(); list.render(); paintFooter();
  profile?.paintStar();
}
app.toggleFavorite = toggleFavorite;

function rowMenu(c, x, y) {
  const fav = S.favorites.some((f) => f.key === c.key);
  const known = !!c.char_id;
  const items = [
    { label: "View profile", disabled: !known, onClick: () => openProfile(c) },
    { label: fav ? "Remove from favorites" : "Add to favorites", disabled: !known, onClick: () => toggleFavorite(c) },
    { label: "Copy name", onClick: () => navigator.clipboard.writeText(c.name) },
    { label: "Refresh", disabled: !known, onClick: () => call("card.refresh", { key: c.key }) },
    { label: "Set Profile", disabled: !known, submenu: () => S.my.slots.map((d, i) => ({
      label: d ? d.name : `Set Character ${i + 1}`, selected: d && `${d.server_id}:${d.char_id}` === c.key,
      onClick: () => setMy("my.set", { key: c.key, slot: i }) })) },
  ];
  if (S.mode === "nearby" && S.nearby.rows.length) items.push("-", { label: "Clear Nearby", onClick: () => call("nearby.clear", { which: "nearby" }) });
  if (S.mode === "recent" && S.nearby.recent.length) items.push("-", { label: "Clear Recent", onClick: () => call("nearby.clear", { which: "recent" }) });
  showMenu(items, x, y);
}

list.box.addEventListener("contextmenu", (e) => {
  if (e.target.closest(".row")) return;
  e.preventDefault();
  const label = S.mode === "nearby" && S.nearby.rows.length ? "Clear Nearby" : S.mode === "recent" && S.nearby.recent.length ? "Clear Recent" : null;
  if (label) showMenu([{ label, onClick: () => call("nearby.clear", { which: S.mode }) }], e.clientX, e.clientY);
});

/* ═════ footer ═════ */
const status = h("span.grow");
const clock = h("span.clock", { onClick: () => { save("clock", S.cfg.clock === "LT" ? "ST" : "LT"); paintClock(); } });
footer.append(status, clock);
function paintClock() {
  const lt = S.cfg.clock === "LT";
  const opts = { month: "2-digit", day: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false };
  const t = new Intl.DateTimeFormat("en-US", lt ? opts : { ...opts, timeZone: "America/New_York" }).format(new Date()).replace(",", "");
  clear(clock).append(h("b", {}, lt ? "LT" : "ST"), t);
}
setInterval(paintClock, 1000 * 15);
function paintFooter() {
  let t = "";
  if (S.screen === "list") {
    const n = list.count;
    if (S.mode === "search" && S.keyword) {
      const total = Object.values(S.regionState).reduce((a, st) => a + (st.total || 0), 0);
      t = total ? `${n} shown of ${fmtInt(total)} matches` : "";
    } else if (S.mode === "favorites") t = `${n} of ${S.favorites.length} favorites`;
  }
  status.textContent = t;
}

/* ═════ render ═════ */
function render() {
  closeMenus();
  paintTitlebar();
  clear(view);
  if (S.screen === "profile" && profile) view.append(profile.el);
  else if (S.screen === "settings" && settings) view.append(settings.el);
  else if (S.screen === "finder" && finder) view.append(finder.el);
  else {
    if (S.mode === "search") view.append(h("div.searchbox", {}, icon("search"), searchInput));
    if (S.mode !== "nearby" || S.nearby.enabled) view.append(filtersBar(), list.head);
    view.append(list.box);
    list.render();
    if (S.mode === "search") setTimeout(() => searchInput.focus(), 0);
  }
  paintFooter();
}
app.render = render;

/* ═════ start ═════ */
(async () => {
  const init = await call("init");
  Object.assign(S, { cfg: init.config, version: init.version, demo: init.demo, regions: init.regions,
    favorites: init.favorites, my: init.my, nearby: init.nearby || S.nearby });
  for (const c of init.favorites) S.chars.set(c.key, c);
  S.update = { ...(await win.update("state")) };
  win.setAlwaysOnTop(S.cfg.always_on_top !== false);
  paintClock();
  if (!S.my.slots.some(Boolean) && !S.cfg.setup_done && !S.demo) openFinder(0);   // first start: find yourself
  else render();
  const q = new URLSearchParams(location.search).get("q");
  if (q) { searchInput.value = q; runSearch(q); }
  window.__app = app;                       // (screenshots / debugging)
})();
