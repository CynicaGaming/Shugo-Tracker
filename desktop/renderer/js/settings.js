// Settings, in the game's style: header bars per group, one setting per row.
import { win } from "./bridge.js";
import { ICONS, LOGO, clear, h } from "./dom.js";

const RECENT = [[50, "50"], [100, "100"], [250, "250"], [500, "500"], [1000, "1,000"], [0, "Unlimited"]];
const AUTOCLEAR = [[0, "Never"], [60, "1m"], [300, "5m"], [900, "15m"], [1800, "30m"], [3600, "60m"]];

const fmtWhen = (t) => {
  const d = new Date(t), today = new Date().toDateString() === d.toDateString();
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return today ? `today, ${time}` : `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`;
};
const fmtBytes = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`);

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
      available: `Version ${next} is available.`, downloading: `Downloading version ${next}… ${pct}%`,
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
    const label = { available: "Download update", downloading: `Downloading ${pct}%`, ready: "Restart to update",
      checking: "Checking…" }[u.state] || "Check now";
    const act = h("button.btn", { class: ["available", "ready"].includes(u.state) ? "gold" : "",
      disabled: ["downloading", "checking", "dev"].includes(u.state), onClick: () => this.updateAction() },
      u.state === "ready" ? h("span", { html: ICONS.refresh, style: { display: "contents" } }) : null, label);
    const when = u.checkedAt ? fmtWhen(u.checkedAt) : "never";
    clear(box).append(h("div.ucard", {}, head, notes),
      h("div.setting", {}, h("div.grow", {}, "Check for updates", h("div.sub", {}, `Last checked ${when}`)), act));
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

    el.append(h("div.bar", {}, "Window"));
    const op = Math.round((cfg.window_opacity ?? 1) * 100);
    const opOut = h("span", { style: { minWidth: "44px", textAlign: "right" } }, `${op}%`);
    el.append(row("Opacity", h("input", { type: "range", min: 30, max: 100, value: op, style: { width: "150px" },
      onInput: (e) => { opOut.textContent = `${e.target.value}%`; win.setOpacity(e.target.value / 100); },
      onChange: (e) => save("window_opacity", e.target.value / 100) }), opOut));
    el.append(row("Always on top", toggle(cfg.always_on_top !== false, (v) => { save("always_on_top", v); win.setAlwaysOnTop(v); this.app.render(); })));

    el.append(h("div.bar", {}, "Nearby", h("span.extra", {}, "BETA")));
    el.append(row("Show Nearby", toggle(!!S.nearby.enabled, async (v) => {
      S.nearby = await call("nearby.enable", { on: v });
      if (v && S.nearby.state === "no_admin") win.relaunchAsAdmin();
    })));
    // What Nearby is doing. Its logs (logs\shugo-core_<time>.log, and the game traffic it read in logs\diagnostics)
    // is always being written, so there's nothing to start when something goes wrong: just send the folder.
    const stat = h("div.sub", {}, "…");
    const STATES = { off: "Off", no_admin: "Needs administrator", no_libs: "Unavailable", starting: "Starting…",
      waiting: "Waiting for AION 2", capturing: "Running", error: "Stopped" };
    const fmtMB = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round((n || 0) / 1024)} KB`);
    const paintStatus = async () => {
      if (!stat.isConnected && this.statusTimer) { clearInterval(this.statusTimer); return; }
      const n = await call("nearby.status");
      const st = n.stats || {};
      const parts = [STATES[n.state] || n.state || "Off"];
      if (n.state === "capturing") parts.push(`${fmtMB(st.bytes)} read`, `${st.players_seen || 0} players seen`);
      else if (n.detail && n.state === "error") parts.push(n.detail);
      stat.textContent = parts.join(" · ");
    };
    el.append(row(h("div", {}, "Status", stat), h("button.btn", { onClick: () => win.openFolder("logs") }, "Open logs")));
    paintStatus();
    this.statusTimer = setInterval(paintStatus, 1000);
    el.append(row("Auto-clear", ...steps(AUTOCLEAR, cfg.nearby_autoclear_s ?? 0, (v) => save("nearby_autoclear_s", v))));
    el.append(row("Recent players", ...steps(RECENT, cfg.recent_max ?? 250, (v) => { cfg.recent_max = v; call("recent.max", { n: v }); }),
      h("button.btn", { onClick: () => call("nearby.clear", { which: "recent" }) }, "Clear")));

    el.append(h("div.bar", {}, "Updates"));
    this.upBox = h("div");
    el.append(this.upBox);
    el.append(row(h("div", {}, "Check automatically", h("div.sub", {}, "Looks for new versions every 30 minutes. Nothing downloads until you click.")),
      toggle(cfg.auto_update !== false, (v) => save("auto_update", v))));
    this.paintUpdate();

    el.append(h("div.bar", {}, "Data"));
    const size = h("div.sub", {}, "…");
    call("cache.size").then((n) => { size.textContent = fmtBytes(n); });
    el.append(row(h("div", {}, "Clear cache", size), h("button.btn", { onClick: async () => { await call("cache.clear"); size.textContent = fmtBytes(await call("cache.size")); } }, "Clear")));
    el.append(row("Application folder", h("button.btn", { onClick: () => win.openFolder() }, "Open")));
  }
}
