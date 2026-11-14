// A character's profile, laid out like the game's windows. The whole profile (info, gear, every item's details)
// is loaded before it's shown, so tabs and tooltips never wait.
import { call, on } from "./bridge.js";
import { CLASS_COLORS, GRADE_COLORS, ICONS, REGION_NAMES, clear, esc, fmtInt, gradeColor, h } from "./dom.js";
import { closeMenus } from "./menu.js";

const TABS = ["Gear", "Skills", "Daevanion", "Stats", "Cosmetics", "Titles"];
const GEAR_MAIN = ["MainHand", "SubHand", "Helmet", "Shoulder", "Torso", "Pants", "Gloves", "Boots", "Cape", "Belt"];
const GEAR_ACC = ["Necklace", "Earring1", "Earring2", "Ring1", "Ring2", "Bracelet1", "Bracelet2", "Amulet", "Rune1", "Rune2"];
const GEAR_ARCANA = Array.from({ length: 10 }, (_, i) => `Arcana${i + 1}`);
const SLOT_NAMES = { MainHand: "Main hand", SubHand: "Off hand", Earring1: "Earring", Earring2: "Earring", Ring1: "Ring",
  Ring2: "Ring", Bracelet1: "Bracelet", Bracelet2: "Bracelet", Rune1: "Rune", Rune2: "Rune", Cape: "Cloak", Torso: "Chest",
  Pants: "Legs" };
const slotName = (s) => SLOT_NAMES[s] || (s.startsWith("Arcana") ? "Arcana" : s);
const PRIMARY = ["STR", "DEX", "INT", "CON", "AGI", "WIS"];
const SKILL_CATS = [["Active", "Active"], ["Passive", "Passive"], ["Dp", "Stigma"]];
const dkey = (it) => `${it.slot}|${it.item_id}|${it.enchant}`;
const worn = (p) => [...GEAR_MAIN, ...GEAR_ACC, ...GEAR_ARCANA].map((s) => p.gear?.[s]).filter((it) => it && it.slot_pos && it.item_id);

let tipEl = null;
function hideTip() { tipEl?.remove(); tipEl = null; }
function showTip(el, x, y, side = "right") {
  hideTip();
  el.classList.add("tip");
  document.body.append(el);
  tipEl = el;
  const r = el.getBoundingClientRect();
  let left = side === "right" ? x + 16 : x - r.width - 16;
  if (left + r.width > innerWidth - 4) left = x - r.width - 16;
  if (left < 4) left = Math.min(innerWidth - r.width - 4, x + 16);
  el.style.left = `${Math.max(4, left)}px`;
  el.style.top = `${Math.max(4, Math.min(y - 20, innerHeight - r.height - 4))}px`;
}
const smallTip = (title, lines, foot) => h("div.small", {}, h("div.t", {}, title), lines.map((l) => h("div.l", {}, l)),
  foot ? h("div.f", {}, foot) : null);

export class ProfileView {
  constructor(app, c) {
    this.app = app;
    this.c = c;
    this.profile = null;
    this.error = null;
    this.ready = false;
    this.details = new Map();          // dkey -> ItemDetail | false
    this.mine = null;                  // your profile (Alt-compare)
    this.myDetails = new Map();
    this.boards = new Map();
    this.tab = TABS.includes(app.S.cfg.profile_tab) ? app.S.cfg.profile_tab : "Gear";
    this.el = h("div.profile");
    this.head = h("div");
    this.tabsEl = h("div.ptabs");
    this.body = h("div.pbody");
    this.el.append(this.head, this.tabsEl, this.body);
    this.offs = [on("profile", (d) => this.onProfile(d))];
    this.paintHead();
    this.paintTabs();
    this.paintBody();
    call("profile.open", { key: c.key });
    this.loadMine();
  }

  destroy() { this.offs.forEach((f) => f()); hideTip(); this.stopAlt(); this.dead = true; }

  /* ───── data ───── */
  onProfile(d) {
    if (this.dead) return;
    if (d.key === this.c.key) {
      if (d.error && this.profile) return;            // keep what we have
      Object.assign(this.c, d.char || {});
      this.profile = d.profile; this.error = d.error;
      this.paintHead();
      if (this.profile && !this.profile.equipment_pending) this.loadItems();
      else this.paintBody();
    } else if (d.key === this.mineKey && d.profile && !d.profile.equipment_pending) {
      this.mine = d.profile;
      if (this.ready) this.loadMyItems();
    }
  }

  async loadItems() {
    const p = this.profile;
    const items = worn(p);
    this.total = items.length;
    const want = items.filter((it) => !this.details.has(dkey(it)));
    if (!this.ready) this.paintBody();
    await Promise.all(want.map(async (it) => {
      try { this.details.set(dkey(it), (await call("item.detail", { key: this.c.key, item: it })) || false); }
      catch { this.details.set(dkey(it), false); }
      if (!this.ready) this.paintRing();
    }));
    if (this.dead || p !== this.profile) return;
    const first = !this.ready;
    this.ready = true;
    this.built = {};
    this.paintBody();
    if (first) this.loadMyItems();
  }

  async loadMine() {
    const me = this.app.myChar();
    if (!me || me.key === this.c.key) { this.mineKey = null; this.mine = null; return; }
    const c = await call("my.character");
    if (!c || this.dead) return;
    this.mineKey = c.key;
    call("profile.open", { key: c.key });
  }
  myChanged() { this.mine = null; this.myDetails.clear(); this.loadMine(); }

  loadMyItems() {
    if (!this.mine || !this.mineKey) return;
    for (const it of worn(this.mine)) {
      if (this.myDetails.has(dkey(it))) continue;
      this.myDetails.set(dkey(it), null);
      call("item.detail", { key: this.mineKey, item: it }).then((d) => this.myDetails.set(dkey(it), d || false)).catch(() => {});
    }
  }

  /* ───── header, stat strip, tabs ───── */
  paintHead() {
    const c = this.c, p = this.profile || {};
    const cls = p.class_name || c.class_name || "Unknown";
    const race = p.race || c.race;
    const server = p.server_name || c.server_name;
    const legion = p.legion || c.legion;
    const fav = this.app.S.favorites.some((f) => f.key === c.key);
    const portrait = p.portrait || c.portrait;
    const bits = [h("span.cls", { style: { color: CLASS_COLORS[cls] || "var(--dim)" } }, cls),
      ` · Lv ${p.level || c.level || "?"}`, server ? ` · ${server} · ${REGION_NAMES[c.region] || c.region}` : "",
      race ? ` · ${race === 1 ? "Elyos" : "Asmodian"}` : ""];
    const wait = this.profile ? "—" : "…";
    clear(this.head).append(
      h("div.phead", {},
        portrait ? h("img.portrait", { src: portrait, onError: (e) => e.target.replaceWith(h("div.portrait")) }) : h("div.portrait"),
        h("div.who", {},
          h("div.name", {}, p.name || c.name, legion ? h("span.legion", {}, `<${legion}>`) : null),
          p.title ? h("div.title", {}, p.title) : null,
          h("div.line", {}, ...bits)),
        h("button.iconbtn", { html: ICONS.refresh, onClick: () => this.reload() }),
        h("button.iconbtn", { class: fav ? "on" : "", html: fav ? ICONS.starFill : ICONS.star, onClick: () => this.app.toggleFavorite(c) })),
      h("div.statstrip", {},
        h("div", {}, h("small", {}, "Combat power"), h("b.cp", {}, (p.combat_power ?? c.combat_power) != null ? fmtInt(p.combat_power ?? c.combat_power) : wait)),
        h("div", {}, h("small", {}, "Gear score"), h("b", {}, (p.gear_score ?? c.gear_score) != null ? fmtInt(p.gear_score ?? c.gear_score) : wait)),
        h("div", {}, h("small", {}, "Level"), h("b", {}, p.level || c.level || wait))));
  }
  paintStar() { this.paintHead(); }

  paintTabs() {
    clear(this.tabsEl);
    for (const t of TABS) this.tabsEl.append(h("button.tab", { class: t === this.tab ? "on" : "", onClick: () => this.show(t) }, t));
  }

  show(t) {
    this.tab = t;
    this.app.save("profile_tab", t);
    this.paintTabs();
    this.paintBody();
  }

  reload() {
    this.details.clear(); this.boards.clear();
    this.profile = null; this.error = null; this.ready = false;
    this.paintHead(); this.paintBody();
    call("profile.open", { key: this.c.key, force: true });
  }

  /* ───── body ───── */
  paintBody() {
    hideTip();
    const b = clear(this.body);
    b.scrollTop = 0;
    if (this.error && !this.profile) {
      b.append(h("div.empty", {}, h("div", {}, h("b", {}, "Couldn't load this profile"), this.error,
        h("div", { style: { marginTop: "12px" } }, h("button.btn.gold", { onClick: () => this.reload() }, "Try again")))));
      return;
    }
    if (!this.ready) { b.append(this.ringEl = this.ring()); this.paintRing(); return; }
    this.built ||= {};
    if (!this.built[this.tab]) this.built[this.tab] = this[`tab${this.tab}`](this.profile);
    b.append(this.built[this.tab]);
  }

  ring() {
    const R = 22, C = 2 * Math.PI * R;
    const svg = h("div", { html: `<svg class="ring" width="56" height="56" viewBox="0 0 56 56"><circle class="bg" cx="28" cy="28" r="${R}"/><circle class="fg" cx="28" cy="28" r="${R}" stroke-dasharray="${C}" stroke-dashoffset="${C * 0.72}"/></svg>` });
    this.ringC = C;
    return h("div.loading", {}, svg, this.ringText = h("div", {}, "Loading profile…"));
  }
  paintRing() {
    if (!this.ringEl) return;
    const ring = this.ringEl.querySelector(".ring"), fg = this.ringEl.querySelector(".fg");
    if (!this.profile || this.profile.equipment_pending) { ring.classList.add("spin"); return; }
    const items = worn(this.profile);
    const done = items.filter((it) => this.details.has(dkey(it))).length;
    ring.classList.remove("spin");
    fg.style.strokeDashoffset = String(this.ringC * (1 - (done + 2) / (items.length + 2)));
    this.ringText.textContent = `Loading gear  ${done} / ${items.length}`;
  }

  /* ───── Gear: the equipment window ───── */
  tile(it, size = 42) {
    if (!it) return h("div.itile.empty", { style: { width: `${size}px`, height: `${size}px` } });
    return h("div.itile", { style: { "--g": gradeColor(it.grade), width: `${size}px`, height: `${size}px` } },
      it.icon ? h("img", { src: it.icon, loading: "lazy" }) : null,
      it.exceed ? h("span.exc", {}, `✦${it.exceed}`) : null,
      it.enchant ? h("span.ench", {}, `+${it.enchant}`) : null);
  }

  tabGear(p) {
    const out = h("div");
    if (p.equipment_error) return h("div.empty", {}, "Couldn't load gear");
    const col = (title, slots) => {
      const c = h("div", {}, h("div.bar", {}, title));
      for (const s of slots) {
        const it = p.gear[s];
        const row = h("div.slot", {}, this.tile(it),
          h("div.txt", {}, it ? h("div.n", { style: { color: gradeColor(it.grade) } }, it.name) : h("div.n", { style: { color: "var(--faint)" } }, slotName(s)),
            it ? h("div.s", {}, `${slotName(s)} · ${it.grade}`) : null));
        if (it?.slot_pos) this.itemHover(row, it);
        c.append(row);
      }
      return c;
    };
    out.append(h("div.gear", {}, col("Equipment", GEAR_MAIN), col("Accessories", GEAR_ACC)));
    const arcana = GEAR_ARCANA.map((s) => p.gear[s]).filter(Boolean);
    if (arcana.length) {
      const row = h("div.arcana");
      for (const it of arcana) {
        const card = h("div.acard", { style: { "--g": gradeColor(it.grade) } }, it.icon ? h("img", { src: it.icon }) : null,
          it.enchant ? h("span.ench", {}, `+${it.enchant}`) : null);
        this.itemHover(card, it);
        row.append(card);
      }
      out.append(h("div.bar", {}, "Arcana"), row);
    }
    return out;
  }

  itemHover(el, it) {
    el.addEventListener("mouseenter", (e) => { this.hoverItem = { it, el, x: e.clientX, y: e.clientY }; this.altState = false; this.drawItemTip(); this.startAlt(); });
    el.addEventListener("mousemove", (e) => { if (this.hoverItem) { this.hoverItem.x = e.clientX; this.hoverItem.y = e.clientY; } });
    el.addEventListener("mouseleave", () => { this.hoverItem = null; this.stopAlt(); hideTip(); });
  }

  startAlt() {
    this.stopAlt();
    const onKey = (e) => { if (e.key === "Alt") { e.preventDefault(); this.setAlt(e.type === "keydown"); } };
    addEventListener("keydown", onKey); addEventListener("keyup", onKey);
    const poll = setInterval(async () => {                 // Alt while the game has focus: ask Windows
      const v = await call("alt").catch(() => null);
      if (v != null) this.setAlt(v);
    }, 90);
    this._alt = () => { removeEventListener("keydown", onKey); removeEventListener("keyup", onKey); clearInterval(poll); };
  }
  stopAlt() { this._alt?.(); this._alt = null; }
  setAlt(v) { if (v !== this.altState) { this.altState = v; if (this.hoverItem) this.drawItemTip(); } }

  drawItemTip() {
    const { it, x, y } = this.hoverItem;
    const det = this.details.get(dkey(it));
    const me = this.mine && this.mineKey;
    if (this.altState && me) {
      const my = this.mine.gear?.[it.slot];
      const myDet = my ? this.myDetails.get(dkey(my)) : null;
      const deltas = det && myDet ? statDeltas(myDet, det) : null;
      const wrap = h("div", { style: { display: "flex", gap: "6px", alignItems: "flex-start", background: "none", border: 0, boxShadow: "none", width: "auto", overflow: "visible" } },
        itemTip(it, det, { deltas }),
        my ? itemTip(my, myDet, { heading: `Equipped  ·  ${this.app.myChar()?.name || ""}` })
          : h("div.tip", { style: { position: "static", width: "300px" } }, h("div.itip", {}, h("div.heading", {}, "EQUIPPED"), h("div.body.faint", {}, "Nothing equipped in this slot"))));
      wrap.querySelectorAll(".tip").forEach((t) => { t.style.position = "static"; });
      showTip(wrap, x, y);
      wrap.style.width = "auto"; wrap.style.background = "none"; wrap.style.border = "0"; wrap.style.boxShadow = "none";
    } else {
      const t = itemTip(it, det, { hint: !!me });
      t.style.position = "fixed";
      showTip(t, x, y);
    }
  }

  /* ───── Stats: the Stat Info window's Main Stats ───── */
  tabStats(p) {
    const out = h("div");
    const by = Object.fromEntries((p.stats || []).map((s) => [s.type, s]));
    const deity = (p.stats || []).filter((s) => !PRIMARY.includes(s.type) && s.type !== "ItemLevel");
    out.append(h("div.bar", {}, "Main Stats"), wheel(by, deity));
    const rows = [];
    for (const s of [...PRIMARY.map((t) => by[t]).filter(Boolean), ...deity]) {
      for (const e of s.effects || []) {
        const m = e.match(/^(.*?)\s*([+-]?\d[\d.,]*%?)$/);
        rows.push(m ? [m[1], m[2]] : [e, ""]);
      }
    }
    if (rows.length) {
      out.append(h("div.bar", {}, "Stat Effects"));
      const kv = h("div.kv");
      for (const [k, v] of rows) kv.append(h("div", {}, h("span", {}, k), h("b", {}, v)));
      if (rows.length % 2) kv.append(h("div"));
      out.append(kv);
    }
    return out;
  }

  /* ───── Skills: the Skill window's Mastery / Stigma grids ───── */
  tabSkills(p) {
    const out = h("div");
    if (p.equipment_error) return h("div.empty", {}, "Couldn't load skills");
    for (const [cat, title] of SKILL_CATS) {
      const skills = (p.skills || []).filter((s) => s.category === cat)
        .sort((a, b) => (b.equipped - a.equipped) || (b.level - a.level) || (a.need_level - b.need_level));
      if (!skills.length) continue;
      out.append(h("div.bar", {}, title));
      const grid = h("div.sgrid");
      for (const s of skills) {
        const stigmaOn = cat === "Dp" && s.level >= 1;
        const t = h("div.stile", { class: [stigmaOn && "on", !s.level && "unlearned"].filter(Boolean).join(" ") },
          s.icon ? h("img", { src: s.icon, loading: "lazy" }) : null,
          s.level || cat === "Dp" ? h("span.lv", {}, `Lv. ${s.level}`) : null);
        t.addEventListener("mouseenter", async (e) => {
          const pos = { x: e.clientX, y: e.clientY };
          t._hover = true;
          const info = await call("skill", { skill_id: s.skill_id, level: s.level || 1, name: s.name, cls: p.class_name });
          if (t._hover) showTip(skillTip(s, info), pos.x, pos.y);
        });
        t.addEventListener("mouseleave", () => { t._hover = false; hideTip(); });
        grid.append(t);
      }
      out.append(grid);
    }
    return out;
  }

  /* ───── Daevanion: the board window ───── */
  tabDaevanion(p) {
    const out = h("div");
    const boards = p.boards || [];
    if (!boards.length) return h("div.empty", {}, "No boards opened");
    const sel = boards.find((b) => b.name === this.app.S.cfg.daevanion_board) || boards[0];
    const tabs = h("div.btabs");
    const pct = (b) => b.game_percent ?? (b.total ? Math.round(100 * b.opened / b.total) : 0);
    for (const b of boards) {
      tabs.append(h("button.tab", { class: b === sel ? "on" : "", onClick: () => { this.app.save("daevanion_board", b.name); this.built.Daevanion = null; this.paintBody(); } },
        b.name, h("small", {}, `${b.opened}/${b.total} · ${pct(b)}%`)));
    }
    const area = h("div");
    out.append(tabs, area);
    const draw = (d) => {
      clear(area);
      if (!d) { area.append(h("div.empty", {}, "Couldn't load this board")); return; }
      area.append(boardEl(d));
      area.append(h("div.bar", {}, "Board Effect", h("span.extra", {}, `${d.opened} nodes`)));
      const fx = h("div.effects");
      for (const e of [...d.stat_effects, ...d.skill_effects]) fx.append(h("div", {}, e));
      if ((d.stat_effects.length + d.skill_effects.length) % 2) fx.append(h("div"));
      area.append(fx);
    };
    const have = this.boards.get(sel.board_id);
    if (have !== undefined) draw(have);
    else {
      area.append(h("div.loading", {}, "Loading board…"));
      call("board", { key: this.c.key, board_id: sel.board_id, opened: sel.opened }).then((d) => {
        this.boards.set(sel.board_id, d);
        if (!this.dead) draw(d);
      });
    }
    return out;
  }

  /* ───── Cosmetics: Wings, Pets, Closet ───── */
  tabCosmetics(p) {
    const out = h("div");
    if (p.equipment_error) return h("div.empty", {}, "Couldn't load cosmetics");
    const item = (it, label) => h("div.slot", {}, this.tile(it),
      h("div.txt", {}, h("div.n", { style: { color: gradeColor(it.grade) } }, it.name),
        h("div.s", {}, [label, it.grade, it.level ? `Lv ${it.level}` : ""].filter(Boolean).join(" · "))));
    const wings = [[p.wing, "Wings"], [p.wing_skin, "Wing appearance"]].filter(([it]) => it);
    if (wings.length) out.append(h("div.bar", {}, "Wings"), h("div.cgrid", {}, wings.map(([it, l]) => item(it, l))));
    if (p.pet) out.append(h("div.bar", {}, "Pet"), h("div.cgrid", {}, item(p.pet, "Pet")));
    if (p.skins?.length) out.append(h("div.bar", {}, "Closet", h("span.extra", {}, `${p.skins.length} items`)),
      h("div.cgrid", {}, p.skins.map((it) => item(it, slotName(it.slot)))));
    return out;
  }

  /* ───── Titles: the Progression tab's title cards ───── */
  tabTitles(p) {
    const out = h("div");
    out.append(h("div.bar", {}, "Title", p.titles_total ? h("span.extra", {}, `${p.titles_owned}/${p.titles_total}`) : null));
    if (!p.titles?.length) { out.append(h("div.empty", {}, "No titles equipped")); return out; }
    const cards = h("div.tcards");
    for (const t of p.titles) {
      cards.append(h("div.tcard", {}, h("div.nm", {}, t.name), t.category ? h("span.cat", {}, t.category) : null,
        t.effects?.length ? h("ul", {}, t.effects.map((e) => h("li", {}, e))) : null,
        t.owned_percent != null ? h("div.own", {}, `Owned by ${t.owned_percent}% of players`) : null));
    }
    out.append(cards);
    return out;
  }
}

/* ═════ pieces ═════ */

function wheel(by, deity) {
  const W = 380, cx = W / 2, cy = 175, R = 150, r = 74;
  const prim = [["STR", "Might", -90], ["DEX", "Dexterity", -30], ["AGI", "Precision", 30], ["WIS", "Willpower", 90],
    ["INT", "Intelligence", 150], ["CON", "Constitution", 210]];
  const pt = (rad, a) => [cx + rad * Math.cos(a * Math.PI / 180), cy + rad * Math.sin(a * Math.PI / 180)];
  let s = `<svg class="wheel" viewBox="0 0 ${W} 350">
    <defs><radialGradient id="wg" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#1d2a3f"/><stop offset="1" stop-color="#0e141e"/></radialGradient></defs>
    <circle cx="${cx}" cy="${cy}" r="${R + 22}" fill="url(#wg)" stroke="rgba(150,170,210,.18)"/>
    <circle cx="${cx}" cy="${cy}" r="${r + 26}" fill="#0f1622" stroke="rgba(99,208,255,.25)"/>
    <circle cx="${cx}" cy="${cy}" r="5" fill="#9fd8ff"/>`;
  for (const [, , a] of prim) { const [x, y] = pt(r + 26, a); s += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="rgba(99,208,255,.12)"/>`; }
  for (const [t, name, a] of prim) {
    const st = by[t], [x, y] = pt(r, a), v = st ? st.value : 0;
    s += `<text class="pn" x="${x}" y="${y - 2}">${esc(name)}</text><text class="pv ${v ? "" : "zero"}" x="${x}" y="${y + 13}">${v}</text>`;
  }
  deity.forEach((d, i) => {
    const a = -90 - 360 / deity.length * 2.5 + i * (360 / deity.length) + 360 / deity.length / 2;
    const [x, y] = pt(R, a);
    const nm = d.name.replace(/\s*\[.*\]/, "");
    s += `<text class="dv ${d.value ? "" : "zero"}" x="${x}" y="${y + 1}">${d.value}</text><text class="dn" x="${x}" y="${y + 14}">${esc(nm)}</text>`;
  });
  return h("div", { html: s + "</svg>" });
}

const GRADE_HEAD = { Common: "#34373e", Rare: "#1e3d27", Legend: "#1b3350", Unique: "#4a3a16", Epic: "#4a2814", Special: "#163f3c", Mythic: "#4a1a2c" };

function fmtDelta(d, pct) {
  const n = Math.abs(d);
  return (d > 0 ? "▲" : "▼") + (Number.isInteger(n) ? n.toLocaleString("en-US") : n.toFixed(1)) + (pct ? "%" : "");
}
const num = (t) => { const m = String(t ?? "").replace(/,/g, "").match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : null; };
function totals(det) {
  const out = {};
  const add = (name, text) => { const n = num(text); if (!name || n == null) return; const [v, p] = out[name] || [0, false]; out[name] = [v + n, p || String(text).includes("%")]; };
  for (const [name, value, extra] of det.main_stats || []) { add(name, value); add(name, extra); }
  for (const [name, value] of det.exceed_stats || []) add(name, value);
  if (det.item_level != null) out["Item Level"] = [det.item_level, false];
  return out;
}
function statDeltas(mine, theirs) {
  const a = totals(mine), b = totals(theirs), out = {};
  for (const [k, [v, pct]] of Object.entries(b)) { const d = Math.round((v - (a[k]?.[0] || 0)) * 100) / 100; if (d) out[k] = [d, pct]; }
  return out;
}

function itemTip(it, det, { heading, deltas, hint } = {}) {
  const col = gradeColor(it.grade), hb = GRADE_HEAD[it.grade] || "#2a2d34";
  deltas ||= {};
  const t = h("div.tip", { style: { position: "static" } });
  const box = h("div.itip");
  t.append(box);
  if (heading) box.append(h("div.heading", {}, heading.toUpperCase()));
  const ilv = det?.item_level != null ? h("div.ilv", {}, `${det.item_level}${it.exceed ? `   ✦${it.exceed}` : ""}`,
    deltas["Item Level"] ? h("span", { class: deltas["Item Level"][0] > 0 ? "up" : "down", style: { fontSize: "13px" } }, fmtDelta(deltas["Item Level"][0])) : null) : null;
  box.append(h("div.head", { style: { background: `linear-gradient(180deg, ${hb}, #121722)` } },
    h("div.t", {}, h("div.nm", { style: { color: col } }, `${it.enchant ? `+${it.enchant} ` : ""}${it.name}`),
      h("div.kind", {}, h("span", { style: { color: col } }, it.grade), det?.category ? ` ${det.category}` : ""),
      ilv ? h("div.il", {}, "Item Level") : null, ilv),
    h("div.itile", { style: { "--g": col, width: "46px", height: "46px" } }, it.icon ? h("img", { src: it.icon }) : null)));
  const body = h("div.body");
  box.append(body);
  if (det === undefined || det === null) { body.append(h("div.faint", { style: { padding: "10px 0", textAlign: "center" } }, "Loading…")); return t; }
  if (det === false) { body.append(h("div.faint", { style: { padding: "10px 0", textAlign: "center" } }, "Couldn't load details")); return t; }
  const shown = new Set();
  const row = (name, value, cls = "", delta) => h("div.r", { class: cls }, h("span", {}, name),
    h("span", { style: { display: "flex", gap: "4px" } }, h("span.v", { class: cls }, value),
      delta ? h("span.delta", { class: delta[0] > 0 ? "up" : "down" }, fmtDelta(...delta)) : null));
  for (const [name, value, extra] of det.main_stats || []) {
    const low = det.main_min?.[name];
    body.append(row(name, `${low ? `${low}–` : ""}${value}${extra ? `(+${extra})` : ""}`, "", shown.has(name) ? null : deltas[name]));
    shown.add(name);
  }
  for (const [name, value] of det.exceed_stats || []) { body.append(row(name, value, "exceed", shown.has(name) ? null : deltas[name])); shown.add(name); }
  const hr = () => body.append(h("div.hr"));
  if (det.soul_bind || det.sub_stats?.length) hr();
  if (det.soul_bind) {
    body.append(row("Soul Binding Rate", `${det.soul_bind}%`, "soul"));
    body.append(h("div", { style: { height: "3px", background: "var(--panel-3)", borderRadius: "2px", margin: "2px 0 4px" } },
      h("div", { style: { height: "100%", width: `${Math.min(100, num(det.soul_bind) || 0)}%`, background: "#5aa9ff", borderRadius: "2px" } })));
  }
  for (const [name, value] of det.sub_stats || []) body.append(row(name, value));
  if (!det.set_name) for (const [name, lv] of det.linked_skills || []) body.append(row(name, `Lvl. +${lv}`));
  if (det.mana_slots || det.mana_stones?.length) {
    hr();
    const st = h("div.stones");
    const stones = [...(det.mana_stones || [])];
    while (stones.length < det.mana_slots) stones.push(null);
    for (const s of stones) {
      if (!s) { st.append(h("span.faint", {}, "◇ Empty")); continue; }
      const [name, value, grade, icon] = s;
      st.append(h("span", { class: grade && grade !== "Common" ? "good" : "" }, icon ? h("img", { src: icon }) : null, `${name}${value}`));
    }
    body.append(st);
  }
  if (det.theo_slots || det.theostones?.length) {
    hr();
    for (const x of det.theostones?.length ? det.theostones : ["Theostone Engravable"]) body.append(h("div.theo", { class: det.theostones?.length ? "" : "faint" }, `◇  ${x}`));
  }
  if (det.set_name) {
    if (det.linked_skills?.length) {
      hr();
      body.append(h("div", { style: { color: "var(--dim)", fontSize: "11px" } }, "LINKED SKILLS"));
      for (const [name, lv, icon] of det.linked_skills) body.append(h("div.r", {}, h("span", { style: { display: "flex", gap: "6px", alignItems: "center" } }, icon ? h("img", { src: icon, style: { width: "18px", height: "18px" } }) : null, name), h("span.v", {}, `Lvl. +${lv}`)));
    }
    hr();
    body.append(h("div", { style: { textAlign: "center", fontWeight: 600, margin: "2px 0 6px" } }, "Set Effects"));
    body.append(h("div", { style: { display: "flex", alignItems: "center", marginBottom: "4px" } }, h("span.setname", {}, det.set_name),
      h("span.badge", { style: { marginLeft: "8px", color: "#fff" } }, h("i", {}, det.set_equipped))));
    for (const [need, effects] of det.set_bonuses || []) {
      const onSet = det.set_equipped >= need;
      effects.forEach((e, i) => body.append(h("div", { style: { display: "flex", alignItems: "flex-start", color: onSet ? "var(--text)" : "var(--faint)", fontSize: "12px", margin: "3px 0" } },
        i === 0 ? h("span.badge", {}, h("i", {}, need)) : h("span", { style: { width: "21px", flex: "none" } }), e)));
    }
  }
  if (det.costumes?.length) { hr(); body.append(h("div", { style: { color: "#4fd1c5" } }, "Skin Info")); det.costumes.slice(0, 3).forEach((c) => body.append(h("div", { style: { color: "var(--gold)", fontSize: "12px" } }, c))); }
  box.append(h("div.foot", {}, h("span", {}, det.equip_level ? `Required Level ${det.equip_level}` : ""),
    h("span", {}, det.max_enchant ? `Max +${det.max_enchant}${det.max_exceed ? ` · ✦${det.max_exceed}` : ""}` : "")));
  if (hint) box.append(h("div.hint", {}, "Hold ALT to compare"));
  return t;
}

function skillTip(s, info) {
  const t = h("div.stip");
  const kind = { Active: ["Active", "#a3342c"], Passive: ["Passive", "#2e6e4c"], Dp: ["Stigma", "#7a3a9a"] }[s.category] || [s.category, "#444"];
  t.append(h("div.head", {}, h("div.t", {}, h("div.nm", {}, s.name),
    s.level || s.category === "Dp" ? h("div.slv", { style: { color: s.level ? "var(--gold)" : "var(--dim)" } }, `Level ${s.level}`) : null,
    h("div.tags", {}, h("span", { style: { background: kind[1] } }, kind[0]))),
    s.icon ? h("img", { src: s.icon }) : null));
  if (info) {
    const desc = h("div.desc");
    let pos = 0;
    for (const [a, b] of info.spans || []) { desc.append(info.text.slice(pos, a), h("b", {}, info.text.slice(a, b))); pos = b; }
    desc.append(info.text.slice(pos));
    t.append(desc);
    const rows = [["Cooldown", info.cooldown], ["MP Cost", info.mp]].filter(([, v]) => v);
    if (rows.length) t.append(h("div.rows", {}, rows.map(([k, v]) => h("div.itip", {}, h("div.r", {}, h("span", {}, k), h("span.v", {}, v))))));
    t.append(h("div.credit", {}, "Info provided by MetaBot.GG"));
  }
  return t;
}

// node colours as the game's board draws them (Unique corners are orange there, not item gold)
const NODE_COLORS = { Common: "#a39d84", Rare: GRADE_COLORS.Rare, Legend: GRADE_COLORS.Legend, Unique: "#e8792b" };

function boardEl(d) {
  const rows = d.nodes.map((n) => n.row), cols = d.nodes.map((n) => n.col);
  const r0 = Math.min(...rows), c0 = Math.min(...cols), nr = Math.max(...rows) - r0 + 1, nc = Math.max(...cols) - c0 + 1;
  const wrap = h("div", { style: { width: "100%" } });
  const el = h("div.board");
  wrap.append(el);
  const layout = () => {
    const w = Math.min(wrap.clientWidth || 560, 460);
    const cell = Math.min(w / nc, 40);
    el.style.width = `${cell * nc}px`; el.style.height = `${cell * nr}px`;
    for (const [n, node] of nodes) {
      const k = n.kind === "Start" ? cell * 0.86 : cell * 0.84;
      Object.assign(node.style, { left: `${(n.col - c0) * cell + (cell - k) / 2}px`, top: `${(n.row - r0) * cell + (cell - k) / 2}px`, width: `${k}px`, height: `${k}px` });
    }
  };
  const nodes = [];
  for (const n of d.nodes) {
    const g = n.grade.toLowerCase();
    const node = h("div.node", { class: [n.kind === "Start" ? "start" : n.kind === "SkillLevel" ? "skill" : "", n.opened ? "open" : "closed", `g-${g}`].join(" "),
      style: { "--g": NODE_COLORS[n.grade] || "#8d8a7c" } });
    node.addEventListener("mouseenter", (e) => showTip(smallTip(n.name || n.kind, n.effects,
      n.kind === "Start" ? null : `${n.grade} · ${n.opened ? "Opened" : "Not opened"}`), e.clientX, e.clientY));
    node.addEventListener("mouseleave", hideTip);
    nodes.push([n, node]);
    el.append(node);
  }
  new ResizeObserver(layout).observe(wrap);
  requestAnimationFrame(layout);
  return wrap;
}
