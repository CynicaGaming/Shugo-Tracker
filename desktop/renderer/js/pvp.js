// PVP Log: everyone you've fought (kills, deaths, assists), and one opponent's fights. Both filter by dates.
import { call, on } from "./bridge.js";
import { CLASS_COLORS, REGION_NAMES, ago, clear, factionColor, fmtInt, h, icon } from "./dom.js";

const SWORDS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
  + '<path d="M14.5 17.5 3 6V3h3l11.5 11.5"/><path d="m13 19 6-6M16 16l4 4M19 21l2-2"/>'
  + '<path d="M14.5 6.5 18 3h3v3l-3.5 3.5"/><path d="m5 14 4 4M7 17l-3 3M3 19l2 2"/></svg>';

/* ───── dates: one pill like the other tabs' Filters; quick ranges or your own From / To; Clear ───── */
const PRESETS = [["today", "Today", 0], ["7d", "Last 7 Days", 6], ["30d", "Last 30 Days", 29]];
let datesOpen = false;

const dayStart = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000;
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parseDay = (s) => { const [y, m, d] = (s || "").split("-").map(Number); return y ? new Date(y, m - 1, d) : null; };
const short = (d) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });

function range(app) {
  const r = app.S.cfg.pvp_range;
  if (r?.preset && PRESETS.some(([k]) => k === r.preset)) return { preset: r.preset };
  if (r && (r.from || r.to)) return { from: r.from || null, to: r.to || null };
  return null;
}

/** {since, until} in epoch seconds for the core (0 = open-ended). */
function bounds(app) {
  const r = range(app);
  if (!r) return { since: 0, until: 0 };
  if (r.preset) {
    const back = PRESETS.find(([k]) => k === r.preset)[2];
    const d = new Date(); d.setDate(d.getDate() - back);
    return { since: dayStart(d), until: 0 };
  }
  const from = parseDay(r.from), to = parseDay(r.to);
  if (to) to.setDate(to.getDate() + 1);                    // through the end of that day
  return { since: from ? dayStart(from) : 0, until: to ? dayStart(to) : 0 };
}

function rangeLabel(app) {
  const r = range(app);
  if (!r) return "All Time";
  if (r.preset) return PRESETS.find(([k]) => k === r.preset)[1];
  const from = parseDay(r.from), to = parseDay(r.to);
  if (from && to) return iso(from) === iso(to) ? short(from) : `${short(from)} – ${short(to)}`;
  return from ? `Since ${short(from)}` : `Until ${short(to)}`;
}

function dateBar(app, onChange) {
  const set = (v) => { app.save("pvp_range", v); onChange(); };
  const r = range(app);
  const box = h("div.filters.pvpdates");
  box.append(h("div.frow2", {},
    h("button.pill.more", { class: datesOpen ? "open" : r ? "on" : "", onClick: () => { datesOpen = !datesOpen; onChange(); } },
      icon("calendar"), rangeLabel(app)),
    h("span.grow"),
    r ? h("button.link", { onClick: () => set(null) }, "Clear") : null));
  if (datesOpen) {
    const today = iso(new Date());
    const custom = r && !r.preset ? r : {};
    const day = (key, other) => h("input.dateinput", { type: "date", value: custom[key] || "", max: key === "from" ? (custom.to || today) : today,
      min: key === "to" ? custom.from || "" : "",
      onChange: (e) => set({ from: custom.from || null, to: custom.to || null, [key]: e.target.value || null, ...other }) });
    box.append(h("div.fpanel", {},
      h("div.flabel", {}, "Quick"),
      h("div.fclasses", {}, PRESETS.map(([k, label]) => h("button.pill", { class: r?.preset === k ? "on" : "",
        onClick: () => { datesOpen = false; set({ preset: k }); } }, label)),
        h("button.pill", { class: r ? "" : "on", onClick: () => { datesOpen = false; set(null); } }, "All Time")),
      h("div.flabel", {}, "Dates"),
      h("div.flevel", {}, day("from"), h("span", {}, "to"), day("to"))));
  }
  return box;
}

function kd(t) {
  if (!t.death) return t.kill ? fmtInt(t.kill) : "—";
  return (t.kill / t.death).toFixed(2);
}

function strip(t) {
  return h("div.statstrip.pvpstrip", {},
    h("div", {}, h("small", {}, "Kills"), h("b.k", {}, fmtInt(t.kill))),
    h("div", {}, h("small", {}, "Deaths"), h("b.d", {}, fmtInt(t.death))),
    h("div", {}, h("small", {}, "Assists"), h("b.a", {}, fmtInt(t.assist))),
    h("div", {}, h("small", {}, "K/D"), h("b", {}, kd(t))));
}

function badge(foe, size = 28) {
  const col = CLASS_COLORS[foe.class_name] || "var(--dim)";
  return h("span.pbadge", { style: { color: col, boxShadow: `inset 0 0 0 1px ${col}55`, width: `${size}px`, height: `${size}px` } },
    foe.portrait ? h("img", { src: foe.portrait, onError: (e) => e.target.replaceWith((foe.class_name || "?")[0]) })
      : (foe.class_name || "?")[0]);
}

const when = (t) => new Intl.DateTimeFormat("en-US", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  hour12: false }).format(new Date(t * 1000)).replace(",", "");

/** The PVP tab: everyone you've fought, newest fight first. */
export class PvpList {
  constructor(app) {
    this.app = app;
    this.el = h("div.pvp");
    this.off = on("pvp", () => this.load());
    this.data = null;
    this.load();
  }
  destroy() { this.off(); }

  async load() {
    this.data = await call("pvp.list", bounds(this.app)).catch(() => ({ foes: [], totals: { kill: 0, death: 0, assist: 0 } }));
    this.paint();
  }

  /** Start fresh: asks first (the fights are kept aside in the data folder, not lost). */
  askClear() { this.asking = true; this.paint(); }

  paint() {
    const el = clear(this.el), d = this.data, { S } = this.app;
    el.oncontextmenu = (e) => { e.preventDefault(); this.app.pvpMenu(e.clientX, e.clientY); };
    if (this.asking) {
      el.append(h("div.pvpask", {},
        h("span.grow", {}, `Clear the PVP Log${this.app.myChar()?.name ? ` for ${this.app.myChar().name}` : ""}? `,
          h("span.faint", {}, "The fights are saved aside in the data folder.")),
        h("button.btn", { onClick: () => { this.asking = false; this.paint(); } }, "Cancel"),
        h("button.btn.danger", { onClick: async () => { this.asking = false; await call("pvp.clear"); this.load(); } }, "Clear")));
    }
    el.append(dateBar(this.app, () => this.load()));
    if (!d) return;
    el.append(strip(d.totals));
    const list = h("div.pvplist");
    if (!d.foes.length) {
      list.append(h("div.empty", {}, h("div", {}, h("b", {}, S.nearby.enabled ? "No Fights Yet" : "PVP Log"),
        S.nearby.enabled ? null : h("div", { style: { maxWidth: "330px", margin: "0 auto 14px" } }, "Who you killed and who killed you, recorded while Nearby is on."),
        S.nearby.enabled ? null : h("button.btn.gold", { onClick: () => this.app.enableNearby() }, "Turn On Nearby"))));
    }
    for (const r of d.foes) {
      const f = r.foe;
      list.append(h("button.pvprow", { onClick: () => this.app.openFoe(r.id) },
        badge(f),
        h("span.who", {}, h("span.nm", { style: { color: f.race ? factionColor(f.race) : "#fff" } }, f.name),
          h("span.sub", {}, [f.class_name, f.server_name].filter(Boolean).join(" · "))),
        h("span.tally", {},
          h("span.k", { class: r.kill ? "" : "zero" }, `${r.kill}`, h("small", {}, "K")),
          h("span.d", { class: r.death ? "" : "zero" }, `${r.death}`, h("small", {}, "D")),
          h("span.a", { class: r.assist ? "" : "zero" }, `${r.assist}`, h("small", {}, "A"))),
        h("span.ago", {}, ago(r.last))));
    }
    el.append(list);
  }
}

/** One opponent: who they are (as on their profile), then their fights with you, newest first. */
export class PvpFoe {
  constructor(app, id) {
    this.app = app;
    this.id = id;
    this.el = h("div.pvp");
    this.card = null;                  // their full card (CP, gear score, legion), once looked up
    this.offs = [on("pvp", () => this.load()),
      on("card", (c) => { if (this.card && c.key === this.card.key) { this.card = { ...this.card, ...c }; this.paint(); } })];
    this.data = null;
    this.load(true);
  }
  destroy() { this.offs.forEach((f) => f()); }

  async load(first = false) {
    this.data = await call("pvp.detail", { id: this.id, ...bounds(this.app) }).catch(() => null);
    this.paint();
    if (first) this.lookUp();
  }

  /** Their card: by key when we have it, otherwise by name on their server. */
  async lookUp() {
    const f = this.data?.foe;
    if (!f) return;
    let c = f.char_id ? { ...f } : null;
    if (!c && f.server_id) {
      const found = await call("find_mine", { name: f.name, server_id: f.server_id }).catch(() => []);
      c = found.find((x) => x.name === f.name) || null;
      if (!c) { this.missing = true; this.paint(); return; }
    }
    if (!c) return;
    this.card = c;
    this.paint();
    call("cards.want", { keys: [c.key] });
  }

  paint() {
    const el = clear(this.el), d = this.data;
    if (!d) return;
    const f = { ...d.foe, ...(this.card || {}) }, cls = f.class_name || "Unknown";
    const wait = this.missing ? "—" : "…";
    const bits = [h("span.cls", { style: { color: CLASS_COLORS[cls] || "var(--dim)" } }, cls),
      f.server_name ? ` · ${f.server_name}` : "", f.region ? ` · ${REGION_NAMES[f.region] || f.region}` : "",
      f.race ? ` · ${f.race === 1 ? "Elyos" : "Asmodian"}` : ""];
    el.append(h("div.phead", {}, f.portrait ? h("img.portrait", { src: f.portrait }) : badge(f, 52),
      h("div.who", {}, h("div.name", {}, f.name, f.legion ? h("span.legion", {}, `<${f.legion}>`) : null),
        h("div.line", {}, ...bits)),
      this.card ? h("button.btn", { onClick: () => this.app.openProfile(this.card) }, "View Profile") : null),
    h("div.statstrip", {},
      h("div", {}, h("small", {}, "Combat Power"), h("b.cp", {}, f.combat_power != null ? fmtInt(f.combat_power) : wait)),
      h("div", {}, h("small", {}, "Gear Score"), h("b", {}, f.gear_score != null ? fmtInt(f.gear_score) : wait)),
      h("div", {}, h("small", {}, "Level"), h("b", {}, f.level || wait))));
    el.append(dateBar(this.app, () => this.load()));
    el.append(strip(d.totals));
    const list = h("div.pvplist");
    if (!d.fights.length) list.append(h("div.empty", {}, h("div", {}, h("b", {}, "No Fights in These Dates"))));
    for (const r of d.fights) list.append(fightRow(r, f));
    el.append(list);
  }
}

/** One fight as the game's kill feed: winner ⚔ loser. Green when you came out on top, red when you didn't. */
function fightRow(r, foe) {
  const me = r.me || "You", them = foe.name;
  const [winner, loser] = r.kind === "death" ? [them, me] : [r.kind === "assist" ? (r.by || "Ally") : me, them];
  const youWon = r.kind !== "death";
  const others = (r.with || []).filter((n) => n !== winner && n !== loser);
  return h("div.fight", { class: r.kind },
    h("span.feed", {},
      h("span.win", { class: youWon ? "us" : "them" }, winner),
      h("span.sw", { html: SWORDS }),
      h("span.lose", {}, loser),
      r.kind === "assist" ? h("span.tag", {}, "Assist") : null,
      r.duel ? h("span.tag.duel", {}, "Duel") : null),
    h("span.with", {}, others.length ? `with ${others.join(", ")}` : ""),
    h("span.ago", {}, ago(r.t)),
    h("span.at", {}, when(r.t)));
}

/** The PVP pop-out: today's kills and deaths, then your latest fights as a kill feed. Click one for that opponent
 *  in the main window. */
export class PvpHud {
  constructor(app) {
    this.app = app;
    this.el = h("div.hud.pvphud");
    this.data = null;
    on("pvp", () => this.load());
    setInterval(() => this.paint(), 30000);              // ("2 min ago" keeps up)
    this.load();
  }

  async load() {
    this.data = await call("pvp.feed", { today_since: dayStart(new Date()), limit: 60 }).catch(() => null);
    this.paint();
    this.onTotals?.(this.data?.today);
  }

  paint() {
    const el = clear(this.el), d = this.data;
    if (!d) return;
    if (!d.fights.length) {
      el.append(h("div.hudnote", {}, h("b", {}, this.app.S.nearby.enabled ? "No Fights Yet" : "Nearby Is Off"),
        this.app.S.nearby.enabled ? null : h("button.btn.gold", { onClick: () => this.app.enableNearby() }, "Turn On")));
      return;
    }
    for (const r of d.fights) {
      const me = r.me || "You", them = r.foe.name;
      const [winner, loser] = r.kind === "death" ? [them, me] : [r.kind === "assist" ? (r.by || "Ally") : me, them];
      el.append(h("div.hudfight", { class: r.kind, onClick: () => this.app.win.showMain({ foe: r.id }) },
        h("span.win", { class: r.kind === "death" ? "them" : "us" }, winner),
        h("span.sw", { html: SWORDS }),
        h("span.lose", {}, loser, r.duel ? h("span.tag.duel", {}, "Duel") : null),
        h("span.ago", {}, ago(r.t).replace(" ago", ""))));
    }
  }
}
