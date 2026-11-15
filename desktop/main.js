// Shugo Tracker (Electron): the window, and the Python core running behind it.
//
// Portable: everything lives in folders next to ShugoTracker.exe (data, cache, logs), Chromium's own cache too.
const { app, BrowserWindow, Menu, ipcMain, screen, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const readline = require("readline");
const { Updater } = require("./updater");

const DEV = !app.isPackaged;
const EXE = process.env.PORTABLE_EXECUTABLE_FILE || app.getPath("exe");     // the file the user started
const ROOT = DEV ? path.join(__dirname, "..", ".dev-app") : path.dirname(EXE);
const SHOWCASE = (process.argv.find((a) => a.startsWith("--showcase=")) || "").slice(11);   // README screenshots
const DEMO = process.argv.includes("--demo") || !!SHOWCASE;
fs.mkdirSync(path.join(ROOT, "cache", "electron"), { recursive: true });
app.setPath("userData", path.join(ROOT, "cache", "electron"));
app.setPath("sessionData", path.join(ROOT, "cache", "electron"));

if (!DEMO && !app.requestSingleInstanceLock()) { app.quit(); process.exit(0); }

let win = null;
let core = null;
let quitting = false;
let opacity = 1;
let pinned = true;                                     // "Always on top" (the pin)

/* Window events go to logs\shugo-window_<start time>.log (one per start, newest 10 kept), so a window that
   vanishes can be explained afterwards. Same naming as the core's logs (shugotracker/logfiles.py). */
const winLog = (() => {
  let f = null;
  try {
    const dir = path.join(ROOT, "logs");
    fs.mkdirSync(dir, { recursive: true });
    const p2 = (n) => String(n).padStart(2, "0"), d = new Date();
    const stamp = `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}_${p2(d.getHours())}-${p2(d.getMinutes())}-${p2(d.getSeconds())}`;
    const old = fs.readdirSync(dir).filter((n) => /^shugo-window_.*\.log$/.test(n)).sort();
    const cutoff = Date.now() - 14 * 86400e3;                            // and nothing older than 14 days
    const age = (n) => { try { return fs.statSync(path.join(dir, n)).mtimeMs; } catch { return Infinity; } };
    const stale = new Set([...old.slice(0, Math.max(0, old.length - 9)), ...old.filter((n) => age(n) < cutoff)]);
    for (const n of stale) try { fs.rmSync(path.join(dir, n)); } catch { /* in use */ }
    for (const n of ["shugo-window.log", "shugo-core.log", "shugo-core-stderr.log"]) try { fs.rmSync(path.join(dir, n)); } catch { /* none */ }
    f = fs.openSync(path.join(dir, `shugo-window_${stamp}.log`), "a");
  } catch { /* read-only folder */ }
  const lineTime = () => {                                              // 2026-11-14 22:51:03.412
    const d = new Date(), p = (n, w = 2) => String(n).padStart(w, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
  };
  return (m) => { if (f != null) try { fs.writeSync(f, `${lineTime()} ${m}\n`); } catch { /* ignore */ } };
})();
const updater = new Updater({ exe: EXE, dir: ROOT, version: app.getVersion(), dev: DEV,
  onChange: (s) => win?.webContents.send("update", s) });

function readConfig() {
  try { return JSON.parse(fs.readFileSync(path.join(ROOT, "data", "config.json"), "utf8")); } catch { return {}; }
}

/* ───── the Python core ───── */
function startCore() {
  const args = ["--root", ROOT, ...(DEMO ? ["--demo"] : []), ...(SHOWCASE ? ["--showcase", SHOWCASE] : [])];
  const cmd = DEV ? (process.env.PYTHON || (process.platform === "win32" ? "python" : "python3")) : path.join(process.resourcesPath, "core", "shugo-core.exe");
  const full = DEV ? ["-m", "shugotracker.core", ...args] : args;
  core = spawn(cmd, full, { cwd: DEV ? path.join(__dirname, "..") : ROOT, windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
  readline.createInterface({ input: core.stdout }).on("line", (line) => {
    try { win?.webContents.send("core", JSON.parse(line)); } catch { /* not JSON: ignore */ }
  });
  core.stderr.on("data", (d) => winLog(`core stderr: ${String(d).trimEnd()}`));
  core.on("exit", (code) => { if (!quitting) win?.webContents.send("core", { event: "core_exit", data: code }); });
}
function toCore(msg) { if (core?.stdin.writable) core.stdin.write(JSON.stringify(msg) + "\n"); }

/* ───── the window ───── */
function createWindow() {
  const cfg = readConfig();
  const [w, h] = Array.isArray(cfg.window_size) ? cfg.window_size : [600, 760];
  const pos = Array.isArray(cfg.window_pos) ? { x: cfg.window_pos[0], y: cfg.window_pos[1] } : {};
  win = new BrowserWindow({
    width: Math.max(380, w), height: Math.max(420, h), ...pos, minWidth: 380, minHeight: 420,
    frame: false, backgroundColor: "#0a0d13", show: false, title: "Shugo Tracker",
    icon: path.join(__dirname, "build", "icon.ico"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false },
  });
  pinned = cfg.always_on_top !== false;
  pin(pinned);
  // Windows quietly drops a window's always-on-top place now and then (another topmost window, the game going
  // borderless/fullscreen, dragging the window): put it back whenever focus leaves it, it moves or comes back,
  // and every few seconds while pinned.
  for (const ev of ["blur", "moved", "show", "restore"]) win.on(ev, () => { if (pinned) setTimeout(() => pin(true, true), 60); });
  setInterval(() => { if (pinned && win && !win.isMinimized() && win.isVisible()) pin(true); }, 3000);
  opacity = Math.max(0.3, Math.min(1, Number(cfg.window_opacity) || 1));
  if (opacity < 1) win.setOpacity(opacity);
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  win.once("ready-to-show", () => { onScreen(); win.show(); });
  for (const ev of ["minimize", "restore", "hide", "show", "maximize", "unmaximize", "unresponsive", "responsive"]) {
    win.on(ev, () => winLog(`window ${ev}`));
  }
  // A see-through window (opacity below 100%) can come back from minimize without repainting, so it stays
  // invisible: set the opacity again and redraw whenever it is restored.
  win.on("restore", () => setTimeout(() => repaint(), 50));
  win.on("maximize", () => win.unmaximize());          // (a double-click on the title bar): keep the overlay size
  win.webContents.on("render-process-gone", (_e, d) => {
    winLog(`renderer gone: ${d.reason}`);
    if (!quitting && win) win.reload();                // a crashed page would leave an empty window
  });
  win.on("close", () => {
    const b = win.getNormalBounds();                   // (a minimized window's bounds are far off screen)
    toCore({ id: 0, method: "config.set", params: { key: "window_size", value: [b.width, b.height] } });
    toCore({ id: 0, method: "config.set", params: { key: "window_pos", value: [b.x, b.y] } });
  });
  win.on("closed", () => { win = null; });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
}

/** Make sure the window is on a screen: monitors change, and a saved position can be off every one of them. */
function onScreen() {
  if (!win) return;
  const b = win.getBounds();
  const area = screen.getDisplayMatching(b).workArea;
  const visible = b.x + b.width > area.x + 60 && b.x < area.x + area.width - 60 && b.y >= area.y - 10 && b.y < area.y + area.height - 60;
  if (!visible) {
    const w = Math.min(b.width, area.width), h = Math.min(b.height, area.height);
    win.setBounds({ x: area.x + Math.round((area.width - w) / 2), y: area.y + Math.round((area.height - h) / 2), width: w, height: h });
    winLog(`moved on screen from ${b.x},${b.y}`);
  }
}
/** Always on top, at the highest level ("screen-saver" stays above borderless games); `force` re-applies it by
 *  switching it off and on, which Windows needs when it has silently dropped it. */
function pin(on, force = false) {
  if (!win) return;
  if (!on) { win.setAlwaysOnTop(false); return; }
  if (force) win.setAlwaysOnTop(false);
  win.setAlwaysOnTop(true, "screen-saver");
}
function repaint() {
  if (!win) return;
  win.setOpacity(opacity);
  win.webContents.invalidate();
}
/** Bring the window back whatever state it is in (starting ShugoTracker.exe again does this). */
function reveal() {
  if (!win) return;
  winLog("reveal");
  if (win.isMinimized()) win.restore();
  onScreen();
  win.show();
  repaint();
  pin(pinned, true);
  win.moveTop();
  win.focus();
}

app.on("second-instance", () => reveal());

ipcMain.on("core", (_e, msg) => toCore(msg));
ipcMain.handle("win", async (_e, action, arg) => {
  switch (action) {
    case "minimize": winLog("minimize button"); win?.minimize(); break;
    case "close": app.quit(); break;
    case "alwaysOnTop": pinned = !!arg; pin(pinned, true); winLog(`always on top: ${pinned}`); break;
    case "opacity": opacity = Math.max(0.3, Math.min(1, Number(arg) || 1)); win?.setOpacity(opacity); break;
    case "openFolder": shell.openPath(arg === "logs" ? path.join(ROOT, "logs") : ROOT); break;
    case "openExternal": shell.openExternal(String(arg)); break;
    case "relaunchAsAdmin": return relaunchAsAdmin();
    case "update": return updater.act(arg);              // "check" | "download" | "restart" | "state"
  }
  return null;
});

/** Nearby reads the game's traffic, which Windows only allows an administrator: start an elevated copy
 *  (Windows asks), and close this one if it started. */
function relaunchAsAdmin() {
  if (process.platform !== "win32") return false;
  winLog("relaunch as administrator");
  app.releaseSingleInstanceLock();                     // let the elevated copy take over the single-instance lock
  const ps = spawn("powershell.exe", ["-NoProfile", "-Command",
    `try { Start-Process -FilePath '${EXE.replace(/'/g, "''")}' -Verb RunAs -WorkingDirectory '${ROOT.replace(/'/g, "''")}'; exit 0 } catch { exit 1 }`],
  { windowsHide: true });
  return new Promise((resolve) => ps.on("exit", (code) => {
    winLog(`relaunch as administrator: ${code === 0 ? "started" : "declined"}`);
    if (code === 0) setTimeout(() => app.quit(), 200);
    else { app.requestSingleInstanceLock(); reveal(); }   // declined: this copy carries on
    resolve(code === 0);
  }));
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);                       // no hidden menu bar for Alt to wake up
  winLog(`Shugo Tracker ${app.getVersion()} started`);
  startCore();
  createWindow();
  updater.start(readConfig().auto_update !== false && !DEMO);
});

app.on("before-quit", () => {
  quitting = true;
  toCore({ method: "quit" });
  setTimeout(() => core?.kill(), 1500);
  updater.onQuit();
});
app.on("window-all-closed", () => app.quit());
