// Shugo Tracker (Electron): the window, and the Python core running behind it.
//
// Portable: everything lives in folders next to ShugoTracker.exe (data, cache, logs), Chromium's own cache too.
const { app, BrowserWindow, ipcMain, shell } = require("electron");
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
  core.stderr.on("data", (d) => fs.appendFile(path.join(ROOT, "logs", "shugo-core-stderr.log"), d, () => {}));
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
    alwaysOnTop: cfg.always_on_top !== false, icon: path.join(__dirname, "build", "icon.ico"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false },
  });
  if (cfg.window_opacity) win.setOpacity(Math.max(0.3, Math.min(1, cfg.window_opacity)));
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  win.once("ready-to-show", () => win.show());
  win.on("close", () => {
    const b = win.getBounds();
    toCore({ id: 0, method: "config.set", params: { key: "window_size", value: [b.width, b.height] } });
    toCore({ id: 0, method: "config.set", params: { key: "window_pos", value: [b.x, b.y] } });
  });
  win.on("closed", () => { win = null; });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
}

app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.show(); win.focus(); } });

ipcMain.on("core", (_e, msg) => toCore(msg));
ipcMain.handle("win", async (_e, action, arg) => {
  switch (action) {
    case "minimize": win?.minimize(); break;
    case "close": app.quit(); break;
    case "alwaysOnTop": win?.setAlwaysOnTop(!!arg); break;
    case "opacity": win?.setOpacity(Math.max(0.3, Math.min(1, Number(arg) || 1))); break;
    case "openFolder": shell.openPath(ROOT); break;
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
  const ps = spawn("powershell.exe", ["-NoProfile", "-Command",
    `try { Start-Process -FilePath '${EXE.replace(/'/g, "''")}' -Verb RunAs -WorkingDirectory '${ROOT.replace(/'/g, "''")}'; exit 0 } catch { exit 1 }`],
  { windowsHide: true });
  return new Promise((resolve) => ps.on("exit", (code) => {
    if (code === 0) { app.releaseSingleInstanceLock(); setTimeout(() => app.quit(), 200); }
    resolve(code === 0);
  }));
}

app.whenReady().then(() => {
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
