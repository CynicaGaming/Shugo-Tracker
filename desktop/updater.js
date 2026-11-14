// Self-update from GitHub Releases, the same way as before: download ShugoTracker.exe and its .sha256 next to
// the running exe, verify, then on "Restart to update" swap them (Windows lets a running exe be renamed) and
// start the new one. Checks at start-up and every 30 minutes; nothing downloads until you click.
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const { app } = require("electron");

const REPO = "CynicaGaming/Shugo-Tracker";
const EXE_ASSET = "ShugoTracker.exe";
const CHECK_EVERY = 30 * 60 * 1000;

const parse = (v) => { const m = /^v?(\d+)\.(\d+)(?:\.(\d+))?$/.exec(String(v).trim()); return m ? [+m[1], +m[2], +(m[3] || 0)] : null; };
const newer = (a, b) => { const x = parse(a), y = parse(b); if (!x || !y) return false; for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i]; return false; };

class Updater {
  constructor({ exe, dir, version, dev, onChange }) {
    Object.assign(this, { exe, dir, version, dev, onChange });
    this.state = { state: "idle", latest: null, progress: 0, error: null };
    this.staged = path.join(dir, `${EXE_ASSET}.new`);
    try { fs.rmSync(`${exe}.old`, { force: true }); } catch { /* still locked: next time */ }
  }

  set(patch) { this.state = { ...this.state, ...patch }; this.onChange?.(this.state); }

  start(auto) {
    if (this.dev) { this.set({ state: "dev" }); return; }
    if (!auto) return;
    this.check();
    this.timer = setInterval(() => { if (["idle", "uptodate", "error"].includes(this.state.state)) this.check(); }, CHECK_EVERY);
  }

  async act(action) {
    if (action === "check") await this.check();
    else if (action === "download") await this.download();
    else if (action === "restart") return this.restart();
    return this.state;
  }

  async check() {
    if (this.dev) return;
    this.set({ state: "checking", error: null });
    try {
      const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, { headers: { "User-Agent": "ShugoTracker" } });
      if (!r.ok) throw new Error(`GitHub ${r.status}`);
      const rel = await r.json();
      this.release = rel;
      const latest = String(rel.tag_name || "").replace(/^v/, "");
      this.set({ latest, state: newer(latest, this.version) ? "available" : "uptodate" });
    } catch (e) { this.set({ state: "error", error: String(e.message || e) }); }
  }

  async download() {
    if (!this.release || this.state.state !== "available") return;
    const asset = (n) => (this.release.assets || []).find((a) => a.name === n);
    const exe = asset(EXE_ASSET), sha = asset(`${EXE_ASSET}.sha256`);
    if (!exe) { this.set({ state: "error", error: "no exe in the release" }); return; }
    this.set({ state: "downloading", progress: 0 });
    try {
      const want = sha ? (await (await fetch(sha.browser_download_url)).text()).trim().split(/\s+/)[0].toLowerCase() : null;
      const r = await fetch(exe.browser_download_url);
      if (!r.ok) throw new Error(`download ${r.status}`);
      const total = Number(r.headers.get("content-length")) || exe.size || 0;
      const hash = crypto.createHash("sha256");
      const out = fs.createWriteStream(this.staged);
      let got = 0;
      for await (const chunk of r.body) {
        hash.update(chunk); out.write(chunk); got += chunk.length;
        if (total) this.set({ progress: got / total });
      }
      await new Promise((res) => out.end(res));
      if (want && hash.digest("hex") !== want) { fs.rmSync(this.staged, { force: true }); throw new Error("checksum mismatch"); }
      this.set({ state: "ready", progress: 1 });
    } catch (e) { this.set({ state: "error", error: String(e.message || e) }); }
  }

  /** Swap in the new exe and start it; this copy then quits. */
  restart() {
    if (this.state.state !== "ready" || !this.swap()) return false;
    spawn(this.exe, ["--after-update"], { detached: true, stdio: "ignore", cwd: this.dir }).unref();
    app.releaseSingleInstanceLock();
    app.quit();
    return true;
  }

  swap() {
    try {
      fs.rmSync(`${this.exe}.old`, { force: true });
      fs.renameSync(this.exe, `${this.exe}.old`);            // allowed while running
      try { fs.renameSync(this.staged, this.exe); } catch (e) { fs.renameSync(`${this.exe}.old`, this.exe); throw e; }
      return true;
    } catch (e) { this.set({ state: "error", error: String(e.message || e) }); return false; }
  }

  /** Quitting with an update downloaded: install it so the next start is the new version. */
  onQuit() {
    clearInterval(this.timer);
    if (this.state.state === "ready" && fs.existsSync(this.staged)) this.swap();
  }
}

module.exports = { Updater };
