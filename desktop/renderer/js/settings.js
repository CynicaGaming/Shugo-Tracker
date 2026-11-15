// Settings, in the game's style: header bars per group, one setting per row.
import { win } from "./bridge.js";
import { LOGO, clear, h, icon } from "./dom.js";

const RECENT = [[50, "50"], [100, "100"], [250, "250"], [500, "500"], [1000, "1,000"], [0, "Unlimited"]];
const UPDATE_EVERY = [[0, "Never"], [1800, "30m"], [3600, "1h"], [21600, "6h"], [43200, "12h"], [86400, "24h"]];
const AUTOCLEAR = [[0, "Never"], [60, "1m"], [300, "5m"], [900, "15m"], [1800, "30m"], [3600, "60m"]];

const fmtWhen = (t) => {
  const d = new Date(t), today = new Date().toDateString() === d.toDateString();
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return today ? `today, ${time}` : `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`;
};

export class SettingsView {
  constructor(app) {
    this.app = app;
    this.el = h("div.scroll");
    this.build();
  }

  /** The Updates card: version and status, what's new, check / download / restart, automatic checks. */
  paintUpdate() {
    const u = this.app.S.update, box = this.upBox;
    if (!box) return;
    const cur = u.current || this.app.S.version, next = u.latest;
    const pct = Math.round((u.progress || 0) * 100);
    const status = {
      checking: "Checking for updates…", uptodate: "You're on the latest version.",
      available: `Version ${next} is available.`, downloading: `Installing version ${next}… ${pct}%`,
      ready: `Version ${next} is ready. Restart Shugo Tracker to finish.`,
      error: `Couldn't update${u.error ? `: ${u.error}` : ""}.`, dev: "Development build: updates are off.",
    }[u.state] || "Not checked yet.";
    const head = h("div.uhead", {}, h("span.ulogo", { html: LOGO }),
      h("div.grow", {}, h("div.ut", {}, `Shugo Tracker v${cur}`), h("div.us", { class: u.state === "error" ? "bad" : "" }, status)));
    if (u.state === "downloading") head.append(h("div.ubar", {}, h("i", { style: { width: `${pct}%` } })));
    const notesFor = ["available", "downloading", "ready"].includes(u.state) ? next : next === cur ? cur : null;
    const notes = notesFor && u.notes?.length
      ? h("div.unotes", {}, h("div.unt", {}, `What's new in ${notesFor}`), h("ul", {}, u.notes.map((n) => h("li", {}, n))))
      : null;
    const label = { available: "Download", downloading: "Installing…", ready: "Restart",
      checking: "Checking…" }[u.state] || "Check Now";
    const act = h("button.btn", { class: ["available", "ready"].includes(u.state) ? "gold" : "",
      disabled: ["downloading", "checking", "dev"].includes(u.state), onClick: () => this.updateAction() },
      u.state === "ready" ? icon("refresh") : null, label);
    const when = u.checkedAt ? fmtWhen(u.checkedAt) : "never";
    clear(box).append(h("div.ucard", {}, head, notes),
      h("div.setting", {}, h("div.grow", {}, "Check for Updates", h("div.sub", {}, `Last checked ${when}`)), act));
  }

  async updateAction() {
    const { S } = this.app;
    const st = S.update.state;
    if (st === "available" || st === "ready") await this.app.updateClick();
    else S.update = { ...(await win.update("check")) };
    this.paintUpdate();
  }

  build() {
    const { S, save, call } = this.app;
    const cfg = S.cfg;
    const el = this.el;
    const toggle = (on, fn) => {
      const t = h("div.toggle", { class: on ? "on" : "", onClick: () => { const v = !t.classList.contains("on"); t.classList.toggle("on", v); fn(v); } });
      return t;
    };
    const row = (label, ...right) => h("div.setting", {}, h("div.grow", {}, label), ...right);
    const steps = (choices, current, onPick) => {
      const i0 = Math.max(0, choices.findIndex(([v]) => v === current));
      const out = h("span", { style: { minWidth: "70px", textAlign: "right", color: "var(--text)" } }, choices[i0][1]);
      const r = h("input", { type: "range", min: 0, max: choices.length - 1, value: i0, style: { width: "150px" },
        onInput: (e) => { out.textContent = choices[e.target.value][1]; }, onChange: (e) => onPick(choices[e.target.value][0]) });
      return [r, out];
    };

    el.append(h("div.bar", {}, "Updates"));
    this.upBox = h("div");
    el.append(this.upBox);
    el.append(row("Check Automatically",
      ...steps(UPDATE_EVERY, cfg.update_check_s ?? 1800, (v) => { save("update_check_s", v); win.update(v); })));
    this.paintUpdate();
    win.update("freshen").then((u) => { if (u) { S.update = { ...S.update, ...u }; this.paintUpdate(); } });

    el.append(h("div.bar", {}, "Window"));
    const op = Math.round((cfg.window_opacity ?? 1) * 100);
    const opOut = h("span", { style: { minWidth: "44px", textAlign: "right" } }, `${op}%`);
    el.append(row("Opacity", h("input", { type: "range", min: 30, max: 100, value: op, style: { width: "150px" },
      onInput: (e) => { opOut.textContent = `${e.target.value}%`; win.setOpacity(e.target.value / 100); },
      onChange: (e) => save("window_opacity", e.target.value / 100) }), opOut));
    el.append(row("Always on Top", toggle(cfg.always_on_top !== false, (v) => { save("always_on_top", v); win.setAlwaysOnTop(v); this.app.render(); })));

    el.append(h("div.bar", {}, "Nearby", h("span.extra", {}, "BETA")));
    el.append(row("Show Nearby", toggle(!!S.nearby.enabled, async (v) => {
      S.nearby = await call("nearby.enable", { on: v });
      if (v && S.nearby.state === "no_admin") win.relaunchAsAdmin();
    })));
    el.append(row("Auto-Clear", ...steps(AUTOCLEAR, cfg.nearby_autoclear_s ?? 0, (v) => save("nearby_autoclear_s", v))));
    el.append(row("Recent Players", ...steps(RECENT, cfg.recent_max ?? 250, (v) => { cfg.recent_max = v; call("recent.max", { n: v }); }),
      h("button.btn", { onClick: () => call("nearby.clear", { which: "recent" }) }, "Clear")));

    el.append(h("div.legal", {}, "Shugo Tracker is a fan-made tool and isn't affiliated with or endorsed by NCSOFT. ",
      "AION and AION 2 are trademarks of NCSOFT Corporation; game names, text and images belong to NCSOFT."));
  }
}
