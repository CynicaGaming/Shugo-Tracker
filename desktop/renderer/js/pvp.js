// PvP Log: everyone you've fought (kills, deaths, assists), and one opponent's fights. Both filter by how far back.
import { call, on } from "./bridge.js";
import { CLASS_COLORS, REGION_NAMES, ago, clear, factionColor, fmtInt, h } from "./dom.js";

export const WITHIN = [[86400, "24h"], [7 * 86400, "7d"], [30 * 86400, "30d"], [0, "All"]];
const KIND = { kill: "Kill", death: "Death", assist: "Assist" };

function within(app) {
  const v = app.S.cfg.pvp_within_s;
  return WITHIN.some(([s]) => s === v) ? v : 0;
}

function seg(app, onChange) {
  const now = within(app);
  return h("div.seg.pvpseg", {}, WITHIN.map(([s, label]) => h("button", { class: s === now ? "on" : "",
    onClick: () => { app.save("pvp_within_s", s); onChange(); } }, label)));
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

/** The PvP tab: everyone you've fought, newest fight first. */
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
    this.data = await call("pvp.list", { within_s: within(this.app) }).catch(() => ({ foes: [], totals: { kill: 0, death: 0, assist: 0 } }));
    this.paint();
  }

  paint() {
    const el = clear(this.el), d = this.data, { S } = this.app;
    el.append(h("div.pvptop", {}, seg(this.app, () => this.load())));
    if (!d) return;
    el.append(strip(d.totals));
    const list = h("div.pvplist");
    if (!d.foes.length) {
      list.append(h("div.empty", {}, h("div", {}, h("b", {}, S.nearby.enabled ? "No Fights Yet" : "PvP Log"),
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

/** One opponent: their fights with you, newest first. */
export class PvpFoe {
  constructor(app, id) {
    this.app = app;
    this.id = id;
    this.el = h("div.pvp");
    this.off = on("pvp", () => this.load());
    this.data = null;
    this.load();
  }
  destroy() { this.off(); }

  async load() {
    this.data = await call("pvp.detail", { id: this.id, within_s: within(this.app) }).catch(() => null);
    this.paint();
  }

  async profile() {
    const f = this.data?.foe;
    if (!f) return;
    if (f.char_id) { this.app.openProfile(f); return; }
    this.looking = true; this.paint();
    const found = await call("find_mine", { name: f.name, server_id: f.server_id }).catch(() => []);
    this.looking = false;
    const c = found.find((x) => x.name === f.name) || found[0];
    if (c) this.app.openProfile(c);
    else { this.missing = true; this.paint(); }
  }

  paint() {
    const el = clear(this.el), d = this.data;
    if (!d) return;
    const f = d.foe, cls = f.class_name || "Unknown";
    const bits = [h("span.cls", { style: { color: CLASS_COLORS[cls] || "var(--dim)" } }, cls),
      f.level ? ` · Lv ${f.level}` : "", f.server_name ? ` · ${f.server_name}` : "",
      f.region ? ` · ${REGION_NAMES[f.region] || f.region}` : "", f.race ? ` · ${f.race === 1 ? "Elyos" : "Asmodian"}` : ""];
    el.append(h("div.phead", {}, f.portrait ? h("img.portrait", { src: f.portrait }) : badge(f, 52),
      h("div.who", {}, h("div.name", {}, f.name), h("div.line", {}, ...bits)),
      f.server_id ? h("button.btn", { disabled: this.looking || this.missing, onClick: () => this.profile() },
        this.missing ? "Not Found" : this.looking ? "Looking…" : "View Profile") : null));
    el.append(h("div.pvptop", {}, seg(this.app, () => this.load())));
    el.append(strip(d.totals));
    const list = h("div.pvplist");
    if (!d.fights.length) list.append(h("div.empty", {}, h("div", {}, h("b", {}, "No Fights in This Time"))));
    for (const r of d.fights) {
      list.append(h("div.fight", { class: r.kind },
        h("span.kind", {}, KIND[r.kind]),
        h("span.with", {}, r.with?.length ? `with ${r.with.join(", ")}` : ""),
        h("span.ago", {}, ago(r.t)),
        h("span.at", {}, when(r.t))));
    }
    el.append(list);
  }
}
