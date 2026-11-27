// Settings, in the game's style: header bars per group, one setting per row.
import { MOBILE, win } from "./bridge.js";
import { SOUNDS, isPlaying, onPlaying, playAlert, soundKind, stopAlert } from "./alert.js";
import { ICONS, LOGO, clear, h, icon } from "./dom.js";

const RECENT = [[50, "50"], [100, "100"], [250, "250"], [500, "500"], [1000, "1,000"], [0, "Unlimited"]];
const ALERT_EVERY = [[10, "10s"], [30, "30s"], [60, "1m"], [120, "2m"], [300, "5m"], [600, "10m"]];
const AUTOCLEAR = [[0, "Never"], [60, "1m"], [300, "5m"], [900, "15m"], [1800, "30m"], [3600, "60m"]];

const fmtWhen = (t) => {
  const d = new Date(t), today = new Date().toDateString() === d.toDateString();
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return today ? `today, ${time}` : `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`;
};

/** A ? beside a setting's name: its explanation shows on hover (or a tap). */
const help = (text) => h("span.help", { tabindex: 0, "data-tip": text }, "?");

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
      available: `Version ${next} is available.`, downloading: `${MOBILE ? "Downloading" : "Installing"} version ${next}… ${pct}%`,
      ready: MOBILE ? `Version ${next} is ready to install.` : `Version ${next} is ready. Restart Shugo Tracker to finish.`,
      error: `Couldn't update${u.error ? `: ${u.error}` : ""}.`, dev: "Development build: updates are off.",
    }[u.state] || "Not checked yet.";
    const head = h("div.uhead", {}, h("span.ulogo", { html: LOGO }),
      h("div.grow", {}, h("div.ut", {}, `Shugo Tracker v${cur}`), h("div.us", { class: u.state === "error" ? "bad" : "" }, status)));
    if (u.state === "downloading") head.append(h("div.ubar", {}, h("i", { style: { width: `${pct}%` } })));
    const notesFor = ["available", "downloading", "ready"].includes(u.state) ? next : next === cur ? cur : null;
    const notes = notesFor && u.notes?.length
      ? h("div.unotes", {}, h("div.unt", {}, `What's new in ${notesFor}`), h("ul", {}, u.notes.map((n) => h("li", {}, n))))
      : null;
    const label = { available: "Download", downloading: MOBILE ? "Downloading…" : "Installing…", ready: MOBILE ? "Install" : "Restart",
      checking: "Checking…" }[u.state] || "Check Now";
    const act = h("button.btn", { class: ["available", "ready"].includes(u.state) ? "gold" : "",
      disabled: ["downloading", "checking", "dev"].includes(u.state), onClick: () => this.updateAction() },
      u.state === "ready" ? icon("refresh") : null, label);
    const when = u.checkedAt ? fmtWhen(u.checkedAt) : "never";
    clear(box).append(h("div.ucard", {}, head, notes),
      h("div.setting", {}, h("div.grow", {}, "Check for Updates", help(`Checked automatically every 15 minutes. Last checked ${when}.`)), act));
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
    this.paintUpdate();
    // anonymous usage statistics (shugotracker/usage.py)
    el.append(h("div.bar", {}, "Privacy"));
    el.append(h("div.setting", {}, h("div.grow", {}, "Share Usage Statistics",
      help("Anonymous: app version, platform and how often features are used. Never names or searches.")),
      toggle(cfg.usage_stats !== false, (v) => save("usage_stats", v))));
    win.update("freshen").then((u) => { if (u) { S.update = { ...S.update, ...u }; this.paintUpdate(); } });

    if (!MOBILE) this.buildDesktop(el, { row, toggle, steps });
  }

  /** Window, Nearby and Notifications: the desktop app's (the phone app has no game window to sit over). */
  buildDesktop(el, { row, toggle, steps }) {
    const { S, save, call } = this.app;
    const cfg = S.cfg;
    el.append(h("div.bar", {}, "Window"));
    const op = Math.round((cfg.window_opacity ?? 1) * 100);
    const opOut = h("span", { style: { minWidth: "44px", textAlign: "right" } }, `${op}%`);
    el.append(row("Opacity", h("input", { type: "range", min: 30, max: 100, value: op, style: { width: "150px" },
      onInput: (e) => { opOut.textContent = `${e.target.value}%`; win.setOpacity(e.target.value / 100); },
      onChange: (e) => save("window_opacity", e.target.value / 100) }), opOut));
    el.append(row("Always on Top", toggle(cfg.always_on_top !== false, (v) => { save("always_on_top", v); win.setAlwaysOnTop(v); this.app.render(); })));

    el.append(h("div.bar", {}, "Nearby"));
    el.append(row("Show Nearby", toggle(!!S.nearby.enabled, async (v) => {
      S.nearby = await call("nearby.enable", { on: v });
      if (v && S.nearby.state === "no_admin") win.relaunchAsAdmin();
    })));
    el.append(row("Auto-Clear", ...steps(AUTOCLEAR, cfg.nearby_autoclear_s ?? 0, (v) => save("nearby_autoclear_s", v))));
    el.append(row("Recent Players", ...steps(RECENT, cfg.recent_max ?? 250, (v) => { cfg.recent_max = v; call("recent.max", { n: v }); })));

    // Notifications: the enemy alert (a sound when an enemy shows up, at most once per "Alert Cooldown")
    el.append(h("div.bar", {}, "Notifications"));
    el.append(row("Enemy Alert", toggle(!!cfg.alert_enemy, (v) => save("alert_enemy", v))));
    el.append(row("Alert Cooldown", ...steps(ALERT_EVERY, cfg.alert_cooldown_s ?? 30, (v) => save("alert_cooldown_s", v))));
    const vol = Math.round((cfg.alert_volume ?? 0.8) * 100);
    const volOut = h("span", { style: { minWidth: "44px", textAlign: "right" } }, `${vol}%`);
    el.append(row("Alert Volume", h("input", { type: "range", min: 0, max: 100, value: vol, style: { width: "150px" },
      onInput: (e) => { volOut.textContent = `${e.target.value}%`; },
      onChange: (e) => { save("alert_volume", e.target.value / 100); playAlert(cfg); } }), volOut));
    // Alert Sound: the built-in sounds, or Custom… (pick a file)
    const pick = h("select.select", { onChange: async (e) => {
      const v = e.target.value;
      if (v === "pick") {
        const r = await win.pickSound();
        if (r && !r.error) { save("alert_sound", r.file); save("alert_sound_name", r.name); save("alert_sound_kind", "custom"); }
        paintPick(r?.error);
      } else { save("alert_sound_kind", v); paintPick(); }
      playAlert(cfg);
    } });
    const err = h("span", { style: { color: "var(--red)", fontSize: "12px" } });
    const paintPick = (error) => {
      const kind = soundKind(cfg);
      clear(pick).append(...Object.entries(SOUNDS).map(([k, [label]]) => h("option", { value: k }, label)),
        ...(cfg.alert_sound ? [h("option", { value: "custom" }, `Custom: ${cfg.alert_sound_name || "your sound"}`)] : []),
        h("option", { value: "pick" }, cfg.alert_sound ? "Choose Another File…" : "Custom…"));
      pick.value = kind === "custom" && !cfg.alert_sound ? "chime" : kind;
      err.textContent = error || "";
    };
    paintPick();
    // play / stop: shows which it'll do
    const play = h("button.btn.playbtn", { onClick: () => (isPlaying() ? stopAlert() : playAlert(cfg)) });
    const paintPlay = (on) => { play.innerHTML = on ? ICONS.stop : ICONS.play; play.classList.toggle("on", on); };
    paintPlay(isPlaying());
    this.offPlay?.();
    this.offPlay = onPlaying(paintPlay);
    el.append(row("Alert Sound", err, pick, play));

  }
}
