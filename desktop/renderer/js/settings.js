// Settings, in the game's style: header bars per group, one setting per row.
import { win } from "./bridge.js";
import { h } from "./dom.js";

const RECENT = [[50, "50"], [100, "100"], [250, "250"], [500, "500"], [1000, "1,000"], [0, "Unlimited"]];
const AUTOCLEAR = [[0, "Never"], [60, "1m"], [300, "5m"], [900, "15m"], [1800, "30m"], [3600, "60m"]];

const fmtBytes = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`);

export class SettingsView {
  constructor(app) {
    this.app = app;
    this.el = h("div.scroll");
    this.build();
  }

  paintUpdate() {
    const u = this.app.S.update;
    const label = { available: `Download update (v${u.latest})`, downloading: `Downloading ${Math.round((u.progress || 0) * 100)}%`,
      ready: "Restart to update", checking: "Checking…", uptodate: "Up to date", dev: "Development build",
      error: "Check for updates" }[u.state] || "Check for updates";
    this.upBtn.textContent = label;
    this.upBtn.classList.toggle("gold", u.state === "available" || u.state === "ready");
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
    el.append(row("Auto-clear", ...steps(AUTOCLEAR, cfg.nearby_autoclear_s ?? 0, (v) => save("nearby_autoclear_s", v))));
    el.append(row("Recent players", ...steps(RECENT, cfg.recent_max ?? 250, (v) => { cfg.recent_max = v; call("recent.max", { n: v }); }),
      h("button.btn", { onClick: () => call("nearby.clear", { which: "recent" }) }, "Clear")));

    el.append(h("div.bar", {}, "Updates"));
    el.append(row("Automatic updates", toggle(cfg.auto_update !== false, (v) => save("auto_update", v))));
    this.upBtn = h("button.btn", { onClick: async () => {
      const st = S.update.state;
      if (st === "available" || st === "ready") await this.app.updateClick();
      else if (st !== "downloading" && st !== "checking") S.update = { ...(await win.update("check")) };
      this.paintUpdate();
    } });
    el.append(row(h("span", {}, `Version ${S.version}`), this.upBtn));
    this.paintUpdate();

    el.append(h("div.bar", {}, "Data"));
    const size = h("div.sub", {}, "…");
    call("cache.size").then((n) => { size.textContent = fmtBytes(n); });
    el.append(row(h("div", {}, "Clear cache", size), h("button.btn", { onClick: async () => { await call("cache.clear"); size.textContent = fmtBytes(await call("cache.size")); } }, "Clear")));
    el.append(row("Application folder", h("button.btn", { onClick: () => win.openFolder() }, "Open")));
  }
}
