// Find your character: region, then server (Elyos and Asmodian side by side), then name. Shown on first start,
// and from your name in the title bar to add another character.
import { CLASS_COLORS, REGION_NAMES, clear, factionColor, h } from "./dom.js";

const REGION_DIGIT = { nae: 1, naw: 2, eu: 3, la: 4, as: 5 };

export class FinderView {
  constructor(app, slot) {
    this.app = app;
    this.slot = slot;
    this.region = null;
    this.server = null;
    this.el = h("div.scroll.finder");
    this.servers = {};
    app.call("servers").then((s) => { this.servers = s; this.paint(); });
    this.paint();
  }

  step(n, label, value, onClick) {
    return h("button.fstep", { class: [n === this.at ? "on" : "", value ? "done" : ""].join(" "), disabled: !onClick, onClick },
      h("span.n", {}, String(n)), h("span", {}, value || label));
  }

  get at() { return this.server ? 3 : this.region ? 2 : 1; }

  paint() {
    const el = clear(this.el);
    el.append(h("div.fhead", {}, h("div.ft", {}, "Find Your Character"),
      h("div.fsteps", {},
        this.step(1, "Region", this.region && REGION_NAMES[this.region], () => { this.region = null; this.server = null; this.paint(); }),
        h("span.sep", {}, "›"),
        this.step(2, "Server", this.server && this.servers[this.server], this.region ? () => { this.server = null; this.paint(); } : null),
        h("span.sep", {}, "›"),
        this.step(3, "Character", null, null))));
    if (!this.region) this.paintRegions(el);
    else if (!this.server) this.paintServers(el);
    else this.paintName(el);
  }

  paintRegions(el) {
    el.append(h("div.bar", {}, "Region"));
    el.append(h("div.fgrid", {}, Object.entries(REGION_NAMES).map(([k, v]) =>
      h("button.fpick", { onClick: () => { this.region = k; this.paint(); } }, v))));
  }

  paintServers(el) {
    const digit = REGION_DIGIT[this.region];
    const side = (race, name) => {
      const ids = Object.keys(this.servers).map(Number)
        .filter((id) => Math.floor(id / 1000) === race && Math.floor(id / 100) % 10 === digit)
        .sort((a, b) => this.servers[a].localeCompare(this.servers[b]));
      return h("div.fcol", {}, h("div.bar", { style: { color: factionColor(race) } }, name),
        h("div.flist", {}, ids.map((id) => h("button.fpick", { onClick: () => { this.server = id; this.paint(); } }, this.servers[id]))));
    };
    el.append(h("div.fcols", {}, side(1, "Elyos"), side(2, "Asmodian")));
  }

  paintName(el) {
    const { call } = this.app;
    el.append(h("div.bar", {}, "Character Name"));
    const results = h("div.fresults");
    let timer = null, asked = 0;
    const run = async (name) => {
      const n = ++asked;
      if (!name.trim()) { clear(results); return; }
      clear(results).append(h("div.fnote", {}, h("span.fspin"), "Searching…"));
      let found;
      try { found = await call("find_mine", { name, server_id: this.server }); }
      catch (e) { if (n === asked) clear(results).append(h("div.fnote", {}, e.message.replace(/^\w+: /, ""))); return; }
      if (n !== asked) return;
      clear(results);
      if (!found.length) { results.append(h("div.fnote", {}, `No one called “${name}” on ${this.servers[this.server]}`)); return; }
      for (const c of found) results.append(this.row(c));
    };
    const input = h("input", { placeholder: "Your character's name", spellcheck: "false",
      onInput: (e) => { clearTimeout(timer); timer = setTimeout(() => run(e.target.value), 350); },
      onKeydown: (e) => { if (e.key === "Enter") { clearTimeout(timer); run(e.target.value); } } });
    el.append(h("div.searchbox", {}, input), results);
    setTimeout(() => input.focus(), 0);
  }

  row(c) {
    const col = CLASS_COLORS[c.class_name] || "var(--dim)";
    return h("button.frow", { onClick: () => this.app.pickMine(c, this.slot) },
      h("span.badge", { style: { color: col, boxShadow: `inset 0 0 0 1px ${col}33` } },
        c.portrait ? h("img", { src: c.portrait, onError: (e) => e.target.replaceWith((c.class_name || "?")[0]) }) : (c.class_name || "?")[0]),
      h("span.nm", {}, c.name),
      c.legion ? h("span.lg", {}, `<${c.legion}>`) : null,
      h("span.grow"),
      h("span", { style: { color: col } }, c.class_name || ""),
      h("span.lv", {}, c.level ? `Lv ${c.level}` : ""));
  }
}
