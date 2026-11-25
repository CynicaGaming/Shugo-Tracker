// The window: title bar, Search / Favorites / Nearby / Recent lists, the PVP Log, menus, footer. Profile and Settings open
// in place of the list (profile.js, settings.js).
import { MOBILE, call, on, win } from "./bridge.js";
import { CLASSES, CLASS_COLORS, COL_LABELS, COL_MENU, DEFAULT_COLUMNS, ICONS, LOGO, REGION_NAMES, ago, clear,
  COL_GAP, COL_MIN, factionColor, fmtInt, h, icon, layoutColumns, sortChars } from "./dom.js";
import { closeMenus, refreshOpenSub, showMenu } from "./menu.js";
import { ProfileView } from "./profile.js";
import { SettingsView } from "./settings.js";
import { AboutView } from "./about.js";
import { FinderView } from "./finder.js";
import { PvpFoe, PvpHud, PvpList } from "./pvp.js";
import { nearbyChanged } from "./alert.js";

const ROW = 38;
const S = {                                    // everything the window shows
  cfg: {}, version: "", demo: false, regions: [],
  mode: "search", screen: "list",              // screen: list | profile | settings | about | finder | foe (PVP Log)
  keyword: "", gen: 0, results: [], regionState: {},
  chars: new Map(), favorites: [], my: { slots: [], active: null },
  nearby: { enabled: false, state: "", rows: [], recent: [] },
  game: true,                                  // AION 2 running: the logo is grey while it isn't
  update: { state: "idle" },                   // the self-updater (desktop/updater.js)
};
export const app = { S, win, call, save, openProfile, closeScreen, myChar, pickMine, refreshList: () => list.render(),
  openFoe: (id) => openFoe(id), enableNearby: () => enableNearby() };

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
  if (POP) { paintHudTitle(); return; }                 // a pop-out has its own slim title bar
  // Redrawn on many events (Nearby, cards, updates): only when something it shows has changed.
  const me0 = myChar(), up0 = S.update;
  const sig = JSON.stringify([S.screen, S.mode, S.favorites.length, S.nearby.enabled, S.nearby.rows.length,
    S.nearby.recent.length, up0.state, up0.latest, Math.round((up0.progress || 0) * 100), up0.clicked,
    S.cfg.always_on_top, me0?.key, me0?.portrait, me0?.name, me0?.server_name, S.my.slots.some(Boolean), S.game]);
  if (sig === titleSig) return;
  titleSig = sig;
  clear(titlebar);
  // An update waiting: a small green blip on the logo's corner (like an app badge); the logo then opens
  // Settings → Updates.
  const up = updateItem();
  titlebar.append(up
    ? h("button.logo.has-update", { class: [up.kind, S.game ? "" : "idle"].join(" "), title: up.label, html: LOGO,
      onClick: () => { if (S.screen !== "settings") openSettings(); } }, h("i.blip"))
    : h("span.logo", { class: S.game ? "" : "idle", html: LOGO }));
  const tabs = h("div.tabs");
  if (S.screen !== "list") {
    const back = { profile: { search: "Search", favorites: "Favorites", nearby: "Nearby", recent: "Recent", pvp: "PVP" }[S.mode], foe: "PVP", settings: "Back", about: "Back", finder: S.my.slots.some(Boolean) ? "Back" : "Skip" }[S.screen];
    tabs.append(h("button.tab.back", { onClick: closeScreen }, icon("back"), back));
  } else {
    const t = (mode, label, count) => h("button.tab", { class: S.mode === mode ? "on" : "", onClick: () => setMode(mode),
      onContextmenu: POPPABLE[mode] && !MOBILE ? (e) => { e.preventDefault(); tabMenu(mode, e.clientX, e.clientY); } : null },
      label, count ? h("span.count", {}, count) : null);
    tabs.append(t("search", "Search"), t("favorites", "Favorites", S.favorites.length || ""));
    if (MOBILE) { /* the phone app has no game to read: no Nearby, Recent or PVP */ }
    else if (S.nearby.enabled) tabs.append(t("nearby", "Nearby", S.nearby.rows.length || ""), t("recent", "Recent", S.nearby.recent.length || ""));
    else tabs.append(t("nearby", "Nearby"));
    if (!MOBILE) tabs.append(t("pvp", "PVP"));
  }
  titlebar.append(tabs, h("span.grow"));
  if (MOBILE) { titlebar.append(meButton()); return; }
  const pinned = S.cfg.always_on_top !== false;
  titlebar.append(h("button.iconbtn", { class: pinned ? "on" : "", html: ICONS.pin, title: "",
    onClick: () => { save("always_on_top", !pinned); win.setAlwaysOnTop(!pinned); paintTitlebar(); } }));
  titlebar.append(meButton(),
    h("button.iconbtn", { html: ICONS.min, onClick: () => win.minimize() }),
    h("button.iconbtn.close", { html: ICONS.close, onClick: () => win.close() }));
}

function meButton() {
  const me = myChar();
  const meBtn = h("button.mebtn", { onClick: (e) => { e.stopPropagation(); meMenu(meBtn); },
    onMousedown: (e) => e.stopPropagation() },
    me?.portrait ? h("img", { src: me.portrait }) : h("span.ph", { html: ICONS.person, style: { color: "var(--dim)", padding: "3px" } }),
    me ? h("span.nm", {}, `${me.name} · ${me.server_name}`) : null);
  return meBtn;
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
  if (me) items.push({ label: "My Profile", onClick: async () => openProfile(await call("my.character")) });
  if (used.length) items.push({ label: "Switch Character", submenu: switchItems });
  const free = S.my.slots.findIndex((d) => !d);
  if (free >= 0) items.push({ label: used.length ? "Add Character" : "Find My Character", onClick: () => openFinder(free) });
  items.push("-", { label: "Settings", onClick: openSettings }, { label: "About", onClick: openAbout });
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
  if (u.state === "error" && u.clicked) return { kind: "bad", label: "Update Failed · Retry" };
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
  const backToFoe = S.screen === "profile" && foe;              // opened from a PVP Log opponent: back to them
  profile?.destroy(); profile = null; settings = null; finder = null; about = null;
  if (backToFoe) { S.screen = "foe"; render(); return; }
  foe?.destroy(); foe = null;
  S.screen = "list";
  render();
}

let profile = null, settings = null, finder = null, foe = null, pvpList = null, about = null;
/** PVP Log: one opponent's fights. */
function openFoe(id) {
  closeMenus();
  foe?.destroy();
  S.screen = "foe";
  foe = new PvpFoe(app, id);
  render();
}
async function enableNearby() {
  S.nearby = await call("nearby.enable", { on: true });
  if (S.nearby.state === "no_admin") win.relaunchAsAdmin();
  render();
}
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
  if (POP) { win.showMain({ profile: c }); return; }    // pop-outs open profiles in the main window
  closeMenus();
  profile?.destroy();
  if (S.screen !== "foe") { foe?.destroy(); foe = null; }
  S.screen = "profile";
  profile = new ProfileView(app, c);
  render();
}
function openAbout() {
  closeMenus();
  S.screen = "about";
  about = new AboutView(app);
  render();
}
function openSettings() {
  S.screen = "settings";
  settings = new SettingsView(app);
  render();
}

const searchInput = h("input", { placeholder: "Search a character name", spellcheck: "false",
  onInput: () => {
    clearTimeout(searchInput._t);
    const kw = searchInput.value.trim();
    if (!kw) clearSearch();                        // emptied: back to the start
    else if (kw.length >= 2) searchInput._t = setTimeout(() => runSearch(kw), 350);
  },
  onKeydown: (e) => { if (e.key === "Enter") runSearch(searchInput.value.trim(), true); } });

function serverFilters() {
  return { classes: S.cfg.classes || [], factions: S.cfg.factions || [], level_min: S.cfg.level_min ?? null, level_max: S.cfg.level_max ?? null };
}

function clearSearch() {
  if (!S.keyword && !S.results.length) return;
  S.keyword = ""; S.searchedFilters = ""; S.results = []; S.regionState = {};
  S.gen += 1;                                     // replies still on their way are ignored
  list.scrollTop(0);
  render();
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
  if (hudOn()) hudSoon();
});

let askedAdmin = false;
on("game", (d) => { S.game = !!d.running; if (POP) render(); else paintTitlebar(); });

on("nearby", (d) => {
  if (!POP) nearbyChanged(d, S.cfg);                    // (the enemy alert: the main window plays it, once)
  const toggled = d.enabled !== S.nearby.enabled;
  S.nearby = d;
  // Nearby is on but this copy isn't administrator (a normal start): restart as administrator once, like
  // turning it on does. Declined: the Nearby tab offers the button.
  if (d.enabled && d.state === "no_admin" && !askedAdmin && !S.demo && !POP) { askedAdmin = true; win.relaunchAsAdmin(); }
  if (toggled && S.screen === "list") { render(); return; }      // filters and headers come and go with it
  for (const r of [...d.rows, ...d.recent]) S.chars.set(r.char.key, r.char);
  if (hudOn()) { hudSoon(); return; }
  if (POP === "pvp") { pvpHud?.paint(); return; }
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
  for (const [v, n] of [["1", "Elyos"], ["2", "Asmodian"]]) {
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

/** Each player's group on Nearby / Recent: the enemy or ally side when we know which faction it is (shown as
 *  Elyos / Asmodian), otherwise Unknown (a catch-all, for anyone the side detection missed). */
function groupsOf(rows) {
  const race = { enemy: list.sideRace("enemy"), ally: list.sideRace("ally") };
  return Object.fromEntries(rows.map((r) => [r.char.name, race[r.side] ? r.side : "unknown"]));
}

function visible() {
  let out = source().map((c) => S.chars.get(c.key) || c);
  const regions = fset("regions"), factions = fset("factions"), classes = fset("classes");
  // A filter only hides players it knows don't match: someone on Nearby whose details haven't come in yet (or
  // couldn't be found) has no region or level, and stays listed rather than vanishing.
  if (regions.size) out = out.filter((c) => !c.region || regions.has(c.region));
  if (factions.size) out = out.filter((c) => !c.race || factions.has(String(c.race)));
  if (classes.size) out = out.filter((c) => !c.class_name || classes.has(c.class_name));
  if (S.cfg.level_min != null) out = out.filter((c) => !c.level || c.level >= S.cfg.level_min);
  if (S.cfg.level_max != null) out = out.filter((c) => !c.level || c.level <= S.cfg.level_max);
  const [key, rev] = (S.cfg.sorts || {})[S.mode] || ["default", false];
  const grouped = S.mode === "nearby" || S.mode === "recent";
  const sideOf = grouped ? groupsOf(S.mode === "recent" ? S.nearby.recent : S.nearby.rows) : null;
  const when = S.mode === "recent" ? Object.fromEntries(S.nearby.recent.map((r) => [r.char.key, r.seen])) : null;
  if (key === "area" && S.mode === "recent") {           // by area name (unknown last), sides still grouped
    const of = Object.fromEntries(S.nearby.recent.map((r) => [r.char.key, areaName(r.area)]));
    const byArea = [...out].sort((a, b) => (!of[a.key] - !of[b.key]) || (of[a.key] || "").localeCompare(of[b.key] || "") * (rev ? -1 : 1));
    return sortChars(byArea, "none", false, sideOf);
  }
  return sortChars(out, key, rev, sideOf, when);
}

function columns() {
  const cols = (S.cfg.columns || DEFAULT_COLUMNS).filter((k) => COL_LABELS[k]);
  return S.mode === "recent" ? cols : cols.filter((k) => k !== "seen" && k !== "area");
}

const list = (() => {
  const head = h("div.thead");
  const box = h("div.list");
  const spacer = h("div.spacer");
  box.append(spacer);
  let rows = [], layout = null, layoutSig = "", frame = 0, drawFrame = 0, wantTimer = 0, resizing = null;
  // Row elements are kept by character and reused while what they show is unchanged, so scrolling and card
  // updates only build the rows that are new or different (and portraits never reload).
  const made = new Map();                                // key -> { el, sig }
  box.addEventListener("scroll", () => { cancelAnimationFrame(drawFrame); drawFrame = requestAnimationFrame(draw); }, { passive: true });
  new ResizeObserver(() => render()).observe(box);

  function render() {
    rows = visible();
    layout = layoutColumns(box.clientWidth || 560, columns(), S.cfg.col_widths || {});
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
    // Between two columns: drag to move the line (the left one grows, the right one shrinks); double-click to
    // put both back to their own size.
    const keys = Object.keys(layout.spans);
    for (let i = 0; i + 1 < keys.length; i++) {
      const [a, b] = [keys[i], keys[i + 1]];
      const x = layout.spans[a][1] + COL_GAP / 2;
      head.append(h("div.rz", { class: resizing === a ? "active" : "", style: { left: `${x - 4}px` },
        onMousedown: (e) => startResize(e, a, b), onClick: (e) => e.stopPropagation(),
        onDblclick: (e) => { e.stopPropagation(); const w = { ...(S.cfg.col_widths || {}) }; delete w[a]; delete w[b]; save("col_widths", w); render(); } }));
    }
    head.oncontextmenu = (e) => { e.preventDefault(); columnsMenu(e.clientX, e.clientY); };
  }

  function startResize(e, a, b) {
    e.preventDefault(); e.stopPropagation();
    const width = (k) => layout.spans[k][1] - layout.spans[k][0];
    const wa = width(a), wb = width(b), x0 = e.clientX;
    // every column but Name keeps the width it has now, so only the two beside the line move
    const frozen = { ...(S.cfg.col_widths || {}) };
    for (const k of Object.keys(layout.spans)) if (k !== "name") frozen[k] = width(k);
    const minA = a === "name" ? 80 : COL_MIN;
    document.body.classList.add("resizing");
    resizing = a;
    const move = (ev) => {
      const d = Math.max(minA - wa, Math.min(wb - COL_MIN, ev.clientX - x0));
      const w = { ...frozen };
      if (a !== "name") w[a] = wa + d;                    // (Name takes whatever the others leave)
      w[b] = wb - d;
      S.cfg.col_widths = w;
      render();
    };
    const up = () => {
      removeEventListener("mousemove", move); removeEventListener("mouseup", up);
      document.body.classList.remove("resizing");
      resizing = null;
      drawHead();
      save("col_widths", S.cfg.col_widths || {});
    };
    addEventListener("mousemove", move); addEventListener("mouseup", up);
  }

  function draw() {
    const top = box.scrollTop, height = box.clientHeight;
    const grouped = S.mode === "nearby" || S.mode === "recent";
    // everything rows need, worked out once per draw
    const ctx = {
      fav: new Set(S.favorites.map((f) => f.key)),
      side: grouped ? new Map(Object.entries(groupsOf(S.mode === "recent" ? S.nearby.recent : S.nearby.rows))) : new Map(),
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
          race === 1 ? "Elyos" : race === 2 ? "Asmodian" : "Unknown"));
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
      c.gear_score, c.combat_power, ctx.fav.has(c.key), side, ctx.race[side], r && ago(r.seen), r?.fought, here, r && areaName(r.area)].join("|");
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
      case "area":
        return h("div.c.dim", { style }, h("span", {}, areaName(r?.area)));
      case "seen":
        return h("div.c", { style: { ...style, color: here ? "var(--green)" : "var(--dim)" } },
          r?.fought ? h("span.fought", {}, "⚔") : null, h("span", {}, here ? "Here Now" : r ? ago(r.seen) : ""));
    }
    return null;
  }

  function rowEl(c, side, ctx, r, here) {
    const fav = ctx.fav.has(c.key);
    const el = h("div.row", {
      onClick: (e) => { if (!e.target.closest(".star") && !e.target.closest(".grip")) openProfile(c); },
      onContextmenu: (e) => { e.preventDefault(); rowMenu(c, e.clientX, e.clientY); } });
    if (side) { const race = ctx.race[side]; el.append(h("span.side", { style: { background: race ? factionColor(race) : "var(--faint)" } })); }
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
    if (S.mode === "search") [t, sub] = S.keyword ? ["No Results", "Try another name or fewer filters"] : ["Search for a Character", ""];
    else if (S.mode === "favorites") [t, sub] = ["No Favorites Yet", ""];
    else if (!S.nearby.enabled) return nearbyOptIn();
    else if (S.mode === "recent") t = S.nearby.recent.length ? "No Results" : "No Recent Players";
    else if (S.nearby.state === "no_admin") {
      return h("div.empty", { style: { position: "absolute", left: 0, right: 0, top: "40px" } }, h("div", {},
        h("b", {}, "Nearby Needs Administrator"),
        h("div", { style: { margin: "0 auto 14px" } }, "Windows only lets administrators read the game's traffic."),
        h("button.btn.gold", { onClick: () => win.relaunchAsAdmin() }, "Restart as Administrator")));
    }
    else t = { waiting: "Waiting for AION 2", starting: "Starting…", error: "Nearby Stopped", capturing: S.nearby.rows.length ? "No Results" : "No Players Nearby" }[S.nearby.state] || "";
    if (S.nearby.state === "error" && S.mode === "nearby") sub = S.nearby.detail || "";
    return h("div.empty", { style: { position: "absolute", left: 0, right: 0, top: "40px" } }, h("div", {}, h("b", {}, t), sub));
  }

  function nearbyOptIn() {
    return h("div.empty", { style: { position: "absolute", left: 0, right: 0, top: "30px" } }, h("div", {},
      h("b", {}, "Nearby"),
      h("div", { style: { maxWidth: "330px", margin: "0 auto 14px" } }, "The players around your character, with their combat power and gear score."),
      h("button.btn.gold", { onClick: () => enableNearby() }, "Turn On Nearby")));
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

  return { head, box, render, renderSoon, sideRace, scrollTop: (y) => { box.scrollTop = y; }, get count() { return rows.length; } };
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
  // only the columns this tab has: Last Seen and Area belong to Recent
  const here = DEFAULT_COLUMNS.filter((k) => S.mode === "recent" || (k !== "seen" && k !== "area"));
  const items = here.map((k) => ({ label: COL_MENU[k], check: cols.includes(k),
    onClick: () => { save("columns", cols.includes(k) ? cols.filter((c) => c !== k) : DEFAULT_COLUMNS.filter((c) => c === k || cols.includes(c))); list.render(); } }));
  items.push("-", { label: "Reset Columns", onClick: () => { save("columns", [...DEFAULT_COLUMNS]); save("col_widths", {}); list.render(); } });
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
  const area = S.mode === "recent" ? S.nearby.recent.find((r) => r.char.key === c.key)?.area : null;
  const items = [
    { label: "View Profile", disabled: !known, onClick: () => openProfile(c) },
    { label: fav ? "Remove from Favorites" : "Add to Favorites", disabled: !known, onClick: () => toggleFavorite(c) },
    { label: "Copy Name", onClick: () => navigator.clipboard.writeText(c.name) },
    { label: "Refresh", disabled: !known, onClick: () => call("card.refresh", { key: c.key }) },
    { label: "Set as My Character", disabled: !known, submenu: () => S.my.slots.map((d, i) => ({
      label: d ? d.name : `Set Character ${i + 1}`, selected: d && `${d.server_id}:${d.char_id}` === c.key,
      onClick: () => setMy("my.set", { key: c.key, slot: i }) })) },
  ];
  if (S.mode === "nearby" && S.nearby.rows.length) items.push("-", { label: "Clear Nearby", onClick: () => call("nearby.clear", { which: "nearby" }) });
  if (area != null) items.push("-", { label: `Name This Area (${areaName(area)})…`, onClick: () => nameArea(area) });
  if (S.mode === "recent" && S.nearby.recent.length) items.push("-", { label: "Clear Recent", onClick: () => call("nearby.clear", { which: "recent" }) });
  showMenu(items, x, y);
}

/* ───── areas: the game only sends a map number; you name them as you go (kept in your settings) ───── */
function areaName(id) {
  if (id == null) return "";
  return (S.cfg.area_names || {})[id] || `Map ${id}`;
}
function nameArea(id) {
  const input = h("input.areainput", { value: (S.cfg.area_names || {})[id] || "", placeholder: `Map ${id}`, spellcheck: "false" });
  const done = (ok) => {
    if (ok) {
      const names = { ...(S.cfg.area_names || {}) }, v = input.value.trim();
      if (v) names[id] = v; else delete names[id];
      save("area_names", names);
    }
    box.remove(); list.render();
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
  const box = h("div.askbox", {}, h("div.askcard", {}, h("b", {}, `Name Map ${id}`), input,
    h("div.askbtns", {}, h("button.btn", { onClick: () => done(false) }, "Cancel"), h("button.btn.gold", { onClick: () => done(true) }, "Save"))));
  box.addEventListener("mousedown", (e) => { if (e.target === box) done(false); });
  document.body.append(box);
  setTimeout(() => input.focus(), 0);
}

list.box.addEventListener("contextmenu", (e) => {
  if (e.target.closest(".row")) return;
  e.preventDefault();
  const label = S.mode === "nearby" && S.nearby.rows.length ? "Clear Nearby" : S.mode === "recent" && S.nearby.recent.length ? "Clear Recent" : null;
  if (label) showMenu([{ label, onClick: () => call("nearby.clear", { which: S.mode }) }], e.clientX, e.clientY);
});

/* ═════ footer ═════ */
const status = h("span.grow");
const CLOCKS = ["ST", "LT", "Both"];                  // a click goes to the next one
const clock = h("span.clock", { onClick: () => { save("clock", CLOCKS[(CLOCKS.indexOf(S.cfg.clock) + 1) % CLOCKS.length]); paintClock(); } });
footer.append(status, clock);
function paintClock() {
  const opts = { month: "2-digit", day: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false };
  const now = new Date();
  const st = new Intl.DateTimeFormat("en-US", { ...opts, timeZone: "America/New_York" }).format(now).replace(",", "");
  const lt = new Intl.DateTimeFormat("en-US", opts).format(now).replace(",", "");
  const mode = CLOCKS.includes(S.cfg.clock) ? S.cfg.clock : "ST";
  clear(clock);
  if (mode !== "LT") clock.append(h("b", {}, "ST"), st);
  if (mode !== "ST") clock.append(h("b", {}, "LT"), lt);
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

/* ═════ HUD style: a slim live Nearby list to keep over the game ═════ */
// This window is a pop-out (index.html?pop=nearby): it only ever shows the HUD.
const POP = new URLSearchParams(location.search).get("pop");
// tabs that can pop out (right-click the tab); Nearby and PVP as slim HUDs, the rest as their usual list
const POPPABLE = { search: "Search", favorites: "Favorites", nearby: "Nearby", recent: "Recent", pvp: "PVP" };
const LIST_POP = ["search", "favorites", "recent"].includes(POP);
const hudOn = () => POP === "nearby";
if (POP) document.title = `Shugo Tracker · ${POPPABLE[POP] || ""}`;    // (its taskbar button)
let pvpHud = null, pvpToday = null;
/** A tab's right-click menu: pop it out, or (popped out already) bring it back under control; PVP can clear its log. */
async function tabMenu(mode, x, y) {
  const open = (await win.popState()).find((p) => p.kind === mode);
  const items = open
    ? [{ label: `Show ${POPPABLE[mode]} Pop-Out`, onClick: () => win.popOut(mode) },
      ...(open.clickThrough ? [{ label: "Turn Off Click Through", onClick: () => win.popClickThroughOff(mode) }] : []),
      { label: "Close Pop-Out", onClick: () => win.popClose(mode) }]
    : [{ label: `Pop Out ${POPPABLE[mode]}`, onClick: () => win.popOut(mode) }];
  if (mode === "pvp") items.push("-", { label: "Clear PVP Log…", onClick: () => {
    if (S.mode !== "pvp" || S.screen !== "list") { S.mode = "pvp"; S.screen = "list"; render(); }
    pvpList?.askClear();
  } });
  showMenu(items, x, y);
}
const pvpMenu = (x, y) => tabMenu("pvp", x, y);
app.pvpMenu = pvpMenu;
let hudFrame = 0;
function hudSoon() { cancelAnimationFrame(hudFrame); hudFrame = requestAnimationFrame(() => { if (hudOn()) render(); }); }

/** From the pop-out, something bigger (a profile, Settings) opens in the main window. */
on("show", (d) => {
  if (POP) return;
  if (d?.profile) openProfile(S.chars.get(d.profile.key) || d.profile);
  else if (d?.foe) { S.mode = "pvp"; openFoe(d.foe); }
  else if (d?.settings) openSettings();
});

const short = (v) => v == null ? "" : v < 1000 ? String(v) : `${(v / 1000).toFixed(v < 100000 ? 1 : 0)}k`;

function paintHudTitle() {
  titleSig = "";                                        // (the full title bar draws itself again afterwards)
  clear(titlebar);
  const n = S.nearby.enabled ? S.nearby.rows.length : 0;
  const t = pvpToday;                                   // PVP: today's kills and deaths
  titlebar.append(h("span.logo", { class: S.game ? "" : "idle", html: LOGO }),
    POP === "pvp"
      ? h("span.hudtitle", {}, "PVP", t ? h("span.today", {}, h("b.k", {}, `${t.kill}`), h("small", {}, "K"), h("b.d", {}, `${t.death}`), h("small", {}, "D"),
        h("b.a", {}, `${t.assist}`), h("small", {}, "A"),
        h("b", {}, t.death ? (t.kill / t.death).toFixed(2) : `${t.kill}`), h("small", {}, "K/D")) : null)
      : h("span.hudtitle", {}, POPPABLE[POP] || "", (POP === "nearby" ? n : POP === "recent" ? S.nearby.recent.length
        : POP === "favorites" ? S.favorites.length : 0) ? h("span.count", {}, POP === "nearby" ? n : POP === "recent"
        ? S.nearby.recent.length : S.favorites.length) : null),
    h("span.grow"),
    h("button.iconbtn", { class: popPanel ? "on" : "", html: ICONS.gear, onClick: () => { popPanel = !popPanel; win.clickThrough({ panel: popPanel }); render(); } }),
    h("button.iconbtn", { html: ICONS.min, onClick: () => win.minimize() }),
    h("button.iconbtn.close", { html: ICONS.close, onClick: () => win.close() }));
}

/* A pop-out's own settings (the gear): opacity, always on top; Nearby's columns and sort live here too. */
const popCfg = () => ({ on_top: true, opacity: 1, ...(S.cfg[`pop_${POP}`] || {}) });
const savePop = (patch) => save(`pop_${POP}`, { ...popCfg(), ...patch });
let popPanel = false;

function popSettings() {
  const c = popCfg();
  const op = Math.round((c.opacity || 1) * 100);
  const out = h("span.v", {}, `${op}%`);
  const onTop = h("div.toggle", { class: c.on_top !== false ? "on" : "", onClick: () => {
    const v = !onTop.classList.contains("on"); onTop.classList.toggle("on", v); savePop({ on_top: v }); win.setAlwaysOnTop(v); } });
  return h("div.poppanel", {},
    h("div.prow", {}, h("span", {}, "Opacity"), h("input", { type: "range", min: 30, max: 100, value: op,
      onInput: (e) => { out.textContent = `${e.target.value}%`; win.setOpacity(e.target.value / 100); },
      onChange: (e) => savePop({ opacity: e.target.value / 100 }) }), out),
    h("div.prow", {}, h("span", {}, "Always on Top"), h("span.grow"), onTop),
    h("div.prow", {}, h("span", {}, "Click Through"), h("span.grow"), toggle(!!c.click_through, (v) => {
      savePop({ click_through: v }); setIgnore(v);       // (the mouse is on this panel: the next move lets it back in)
    })),
    h("div.prow", {}, h("span", {}, "Lock Position"), h("span.grow"), toggle(!!c.locked, (v) => {
      savePop({ locked: v }); win.lock(v); root.classList.toggle("locked", v);
    })));
}
const toggle = (on, fn) => {
  const t = h("div.toggle", { class: on ? "on" : "", onClick: () => { const v = !t.classList.contains("on"); t.classList.toggle("on", v); fn(v); } });
  return t;
};

/* Click Through: the game gets your clicks, except on the title bar; hold Alt (or open the gear) to use all of it.
   The main process watches the cursor (a window that ignores the mouse can't): this tells it the switches. */
let altDown = false;
function setIgnore(on) { win.clickThrough({ on }); }
const clickThrough = () => POP && popCfg().click_through;
if (POP) {
  setInterval(async () => {                             // Alt while the game has focus: ask Windows
    if (!clickThrough()) { if (altDown) { altDown = false; win.clickThrough({ alt: false }); } return; }
    const v = await call("alt").catch(() => null);
    if (v != null && v !== altDown) { altDown = v; win.clickThrough({ alt: v }); }
  }, 150);
  on("popcfg", (d) => { savePop(d); render(); });       // (changed from the main window's tab menu)
}

// Nearby pop-out columns: Name always, the rest your choice (right-click the header); click a header to sort.
const HUD_COLS = {
  name: ["Name", "minmax(0, 1fr)"], legion: ["Legion", "64px"], class: ["Class", "34px"], level: ["Lv", "20px"],
  server: ["Server", "64px"], gs: ["GS", "36px"], cp: ["CP", "42px"],
};
const HUD_ORDER = ["legion", "class", "level", "server", "gs", "cp"];
const HUD_DEFAULT = ["class", "gs", "cp"];
const hudCols = () => ["name", ...HUD_ORDER.filter((k) => (popCfg().columns || HUD_DEFAULT).includes(k))];

function hudHeadMenu(e) {
  e.preventDefault();
  const cols = popCfg().columns || HUD_DEFAULT;
  showMenu([...HUD_ORDER.map((k) => ({ label: COL_MENU[k], check: cols.includes(k),
    onClick: () => { savePop({ columns: cols.includes(k) ? cols.filter((x) => x !== k) : [...cols, k] }); render(); } })),
    "-", { label: "Reset Columns", onClick: () => { savePop({ columns: [...HUD_DEFAULT], sort: null }); render(); } }], e.clientX, e.clientY);
}

function hudSort(k) {
  const [key, rev] = popCfg().sort || ["default", false];
  savePop({ sort: key !== k ? [k, false] : rev ? null : [k, true] });
  render();
}

function hudBody() {
  const box = h("div.hud");
  const nb = S.nearby;
  const note = (title, button) => box.append(h("div.hudnote", {}, h("b", {}, title), button || null));
  if (!nb.enabled) { note("Nearby Is Off", h("button.btn.gold", { onClick: () => enableNearby() }, "Turn On")); return box; }
  if (nb.state === "no_admin") { note("Needs Administrator", h("button.btn.gold", { onClick: () => win.relaunchAsAdmin() }, "Restart as Administrator")); return box; }
  if (nb.state === "waiting" || nb.state === "starting") { note(nb.state === "waiting" ? "Waiting for AION 2" : "Starting…"); return box; }
  if (nb.state === "error") { note("Nearby Stopped"); return box; }
  const cols = hudCols();
  const grid = { gridTemplateColumns: cols.map((k) => HUD_COLS[k][1]).join(" ") };
  const [key, rev] = popCfg().sort || ["default", false];
  // enemies first (the stripe shows the side); within each, your sort or else highest CP first
  const sideOf = groupsOf(nb.rows);
  const chars = nb.rows.map((r) => S.chars.get(r.char.key) || r.char);
  const sorted = sortChars(chars, key === "default" ? "cp" : key, key === "default" ? false : rev, sideOf);
  box.append(h("div.hudhead", { style: grid, onContextmenu: hudHeadMenu }, cols.map((k) => {
    const natural = ["level", "gs", "cp"].includes(k);
    return h("span", { class: [key === k ? "sorted" : "", natural ? "num" : ""].join(" "),
      "data-arrow": (natural !== !!rev) ? "▼" : "▲", onClick: () => hudSort(k) }, HUD_COLS[k][0]);
  })));
  if (!sorted.length) { note("No Players Nearby"); return box; }
  const want = [];
  for (const c of sorted) {
    const side = sideOf[c.name], race = list.sideRace(side);
    const loading = c.status === "loading" || c.status === "none" || !c.status;
    if (c.status === "none" || !c.status || c.stale) want.push(c.key);
    const ph = (v, f) => v != null ? f(v) : loading ? h("i.ph") : "";
    const cell = {
      name: () => h("span.nm", {}, c.name),
      legion: () => h("span.dim", {}, c.legion || ""),
      class: () => h("span.cl", { style: { color: CLASS_COLORS[c.class_name] || "var(--dim)" } }, (c.class_name || "?").slice(0, 3)),
      level: () => h("span.num", {}, c.level || ""),
      server: () => h("span.dim", {}, c.server_name || ""),
      gs: () => h("span.num.gs", {}, ph(c.gear_score, short)),
      cp: () => h("span.num.cp", {}, ph(c.combat_power, short)),
    };
    box.append(h("div.hudrow", { style: grid, onClick: () => win.showMain({ profile: c }) },
      h("span.side", { style: { background: race ? factionColor(race) : "var(--faint)" } }),
      cols.map((k) => cell[k]())));
  }
  if (want.length) call("cards.want", { keys: want });
  return box;
}

/* ═════ render ═════ */
function render() {
  closeMenus();
  root.classList.toggle("hudstyle", !!POP);
  root.classList.toggle("locked", !!(POP && popCfg().locked));
  if (POP === "pvp") {
    if (!pvpHud) { pvpHud = new PvpHud(app); pvpHud.onTotals = (t) => { pvpToday = t; paintHudTitle(); }; }
    paintHudTitle();
    clear(view).append(...(popPanel ? [popSettings()] : []), pvpHud.el);
    return;
  }
  if (hudOn()) {
    paintHudTitle();
    const top = view.querySelector(".hud")?.scrollTop || 0;
    clear(view).append(...(popPanel ? [popSettings()] : []), hudBody());
    view.querySelector(".hud").scrollTop = top;
    return;
  }
  paintTitlebar();
  clear(view);
  if (LIST_POP && popPanel) view.append(popSettings());
  if (S.screen === "profile" && profile) view.append(profile.el);
  else if (S.screen === "settings" && settings) view.append(settings.el);
  else if (S.screen === "about" && about) view.append(about.el);
  else if (S.screen === "finder" && finder) view.append(finder.el);
  else if (S.screen === "foe" && foe) view.append(foe.el);
  else if (S.mode === "pvp") {
    pvpList ??= new PvpList(app);
    pvpList.load();
    view.append(pvpList.el);
  } else {
    if (S.mode === "search") view.append(h("div.searchbox", {}, icon("search"), searchInput));
    if (S.mode !== "nearby" || S.nearby.enabled) view.append(filtersBar(), list.head);
    view.append(list.box);
    list.render();
    if (S.mode === "search" && !MOBILE) setTimeout(() => searchInput.focus(), 0);   // (a phone would pop its keyboard)
  }
  paintFooter();
}
app.render = render;

// A phone has no hover: a tap is the hover (tooltips show on a tap, and go on the next tap, or a second tap on
// the same thing).
if (MOBILE) {
  let hovered = [], last = null;
  // (the browser's own hover events from a touch come and go unpredictably: only ours count)
  for (const t of ["mouseenter", "mouseleave", "mouseover", "mouseout"]) {
    document.addEventListener(t, (e) => { if (e.isTrusted) e.stopPropagation(); }, true);
  }
  const fire = (n, type, e) => n.dispatchEvent(new MouseEvent(type, { clientX: e.clientX, clientY: e.clientY, screenX: e.screenX, screenY: e.screenY }));
  document.addEventListener("click", (e) => {
    if (e.target.closest?.(".tip")) return;            // (a tap inside a tooltip is for the tooltip)
    const chain = [];
    for (let n = e.target; n && n !== document; n = n.parentNode) chain.push(n);
    const again = e.target === last;
    hovered.filter((n) => again || !chain.includes(n)).forEach((n) => fire(n, "mouseleave", e));
    if (again) { hovered = []; last = null; return; }
    chain.filter((n) => !hovered.includes(n)).reverse().forEach((n) => fire(n, "mouseenter", e));
    hovered = chain; last = e.target;
  }, true);
}

// Android's back button: back a screen (or out of a menu); false on the main list, so the app closes.
window.__shugoBack = () => {
  if (document.querySelector(".menu")) { closeMenus(); return true; }
  if (S.screen !== "list") { closeScreen(); return true; }
  if (S.mode !== "search") { setMode("search"); return true; }
  return false;
};

/* ═════ start ═════ */
(async () => {
  const init = await call("init");
  if (MOBILE && !["search", "favorites"].includes(S.mode)) S.mode = "search";
  if (LIST_POP) S.mode = POP;                           // a popped-out list is always that tab
  Object.assign(S, { cfg: init.config, version: init.version, demo: init.demo, regions: init.regions,
    favorites: init.favorites, my: init.my, nearby: init.nearby || S.nearby, game: init.game !== false });
  if (!POP) nearbyChanged(S.nearby, S.cfg);
  for (const c of init.favorites) S.chars.set(c.key, c);
  S.update = { ...(await win.update("state")) };
  if (!POP) win.setAlwaysOnTop(S.cfg.always_on_top !== false);   // (a pop-out has its own, set by the window)
  paintClock();
  if (Array.isArray(S.cfg.columns) && !S.cfg.columns.includes("area") && !S.cfg.area_column_added && !POP) {
    save("columns", [...S.cfg.columns, "area"]); save("area_column_added", true);   // (new in 2.6.2: shown once)
  }
  const q = new URLSearchParams(location.search).get("q");
  if (!POP && !q && !S.my.slots.some(Boolean) && !S.cfg.setup_done && !S.demo) openFinder(0);   // first start: find yourself
  else render();
  if (q) { searchInput.value = q; runSearch(q); }
  window.__app = app;                       // (screenshots / debugging)
})();
