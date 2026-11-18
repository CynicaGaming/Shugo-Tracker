// Shugo Tracker (Electron): the window, and the Python core running behind it.
//
// Portable: everything lives in folders next to ShugoTracker.exe (data, cache, logs), Chromium's own cache too.
const { app, BrowserWindow, Menu, ipcMain, nativeImage, screen, shell } = require("electron");
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
  // logs\shugo-window_<day>.log: one file a day (every start that day adds to it), 14 days kept, the same as
  // the core's logs (shugotracker/logfiles.py).
  const dir = path.join(ROOT, "logs");
  const p2 = (n, w = 2) => String(n).padStart(w, "0");
  const day = (d = new Date()) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
  let f = null, openDay = "";
  const open = () => {
    openDay = day();
    try {
      fs.mkdirSync(dir, { recursive: true });
      const cutoff = day(new Date(Date.now() - 14 * 86400e3));
      for (const n of fs.readdirSync(dir)) {
        const m = /^shugo-window_(\d{4}-\d\d-\d\d)/.exec(n);
        if (m && m[1] <= cutoff) try { fs.rmSync(path.join(dir, n)); } catch { /* in use */ }
      }
      if (f != null) fs.closeSync(f);
      f = fs.openSync(path.join(dir, `shugo-window_${openDay}.log`), "a");
    } catch { f = null; /* read-only folder */ }
  };
  const lineTime = () => {                                              // 2026-11-14 22:51:03.412
    const d = new Date();
    return `${day(d)} ${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}.${p2(d.getMilliseconds(), 3)}`;
  };
  return (m) => {
    if (openDay !== day()) open();                                        // (midnight: the next day's file)
    if (f != null) try { fs.writeSync(f, `${lineTime()} ${m}\n`); } catch { /* ignore */ }
  };
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
    let msg;
    try { msg = JSON.parse(line); } catch { return; }    // not JSON: ignore
    try {
      if (msg.event === "game") gameIcon(!!msg.data?.running);
      else if (msg.result && typeof msg.result.game === "boolean" && "nearby" in msg.result) gameIcon(msg.result.game);   // (init)
    } catch (e) { winLog(`taskbar icon: ${e.message}`); }
    // a reply goes to the window that asked (each window numbers its own requests); events go to every window
    if (msg.id != null && routes.has(msg.id)) {
      const { wc, id } = routes.get(msg.id);
      routes.delete(msg.id);
      if (!wc.isDestroyed()) wc.send("core", { ...msg, id });
    } else if (msg.event) for (const w of allWindows()) w.webContents.send("core", msg);
  });
  core.stderr.on("data", (d) => winLog(`core stderr: ${String(d).trimEnd()}`));
  // A write to a core that has just exited fails later, on its own: catch it here so it can never become an
  // "uncaught exception" dialog.
  core.stdin.on("error", (e) => winLog(`core pipe: ${e.code || e.message}`));
  core.on("exit", (code) => {
    winLog(`core exited (${code})`);
    if (!quitting) win?.webContents.send("core", { event: "core_exit", data: code });
  });
}
const routes = new Map();                               // core request id -> {window, its own id}
let nextId = 1;
function fromWindow(wc, msg) {
  if (msg.id) { const id = nextId++; routes.set(id, { wc, id: msg.id }); msg = { ...msg, id }; }
  toCore(msg);
}
function toCore(msg) { if (core?.stdin.writable && !core.stdin.destroyed) core.stdin.write(JSON.stringify(msg) + "\n"); }

const MAIN = { size: "window_size", pos: "window_pos", def: [600, 760], min: [380, 420] };
// Pop-outs: a tab in its own slim always-on-top window. Each kind keeps its own size and place.
const POPS = {
  nearby: { size: "hud_size", pos: "hud_pos", def: [270, 360], min: [210, 120], open: "popout_nearby", title: "Nearby" },
  pvp: { size: "pvp_pop_size", pos: "pvp_pop_pos", def: [300, 300], min: [220, 120], open: "popout_pvp", title: "PVP" },
};

/** A window's size and place, saved through the core (data\\config.json). */
function saveBounds(w = win, k = MAIN) {
  if (!w || w.isDestroyed()) return;
  const b = w.getNormalBounds();                       // (a minimized window's bounds are far off screen)
  toCore({ id: 0, method: "config.set", params: { key: k.size, value: [b.width, b.height] } });
  toCore({ id: 0, method: "config.set", params: { key: k.pos, value: [b.x, b.y] } });
}

function savedBounds(k, cfg) {
  const [w, h] = Array.isArray(cfg[k.size]) ? cfg[k.size] : k.def;
  const pos = Array.isArray(cfg[k.pos]) ? { x: cfg[k.pos][0], y: cfg[k.pos][1] } : {};
  return { ...pos, width: Math.max(k.min[0], w), height: Math.max(k.min[1], h), minWidth: k.min[0], minHeight: k.min[1] };
}

/* ───── Pop Out: a tab in its own slim always-on-top window ───── */
const pops = {};                                        // kind -> BrowserWindow
const allWindows = () => [win, ...Object.values(pops)].filter((w) => w && !w.isDestroyed());
const popKind = (wc) => Object.keys(pops).find((k) => pops[k] && !pops[k].isDestroyed() && pops[k].webContents === wc);

function popOut(kind) {
  const P = POPS[kind];
  if (!P) return;
  if (pops[kind]) { pops[kind].show(); pops[kind].focus(); return; }
  const cfg = readConfig();
  const b = savedBounds(P, cfg);
  if (b.x == null && win) {                             // first time: beside the window
    const m = win.getBounds(), n = Object.keys(pops).length;
    b.x = m.x + m.width + 8; b.y = m.y + n * 40;
  }
  const w = pops[kind] = new BrowserWindow({
    ...b, frame: false, backgroundColor: "#0a0d13", show: false, title: `Shugo Tracker · ${P.title}`,
    icon: path.join(__dirname, "build", "icon.ico"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false },
  });
  // its own opacity and always-on-top (the gear in its title bar)
  const own = cfg[`pop_${kind}`] || {};
  w.onTop = own.on_top !== false;
  if (w.onTop) w.setAlwaysOnTop(true, "screen-saver");
  for (const ev of ["blur", "moved", "show", "restore"]) w.on(ev, () => setTimeout(() => {
    if (!w.isDestroyed() && w.onTop) { w.setAlwaysOnTop(false); w.setAlwaysOnTop(true, "screen-saver"); }
  }, 60));
  const op = Math.max(0.3, Math.min(1, Number(own.opacity) || 1));
  if (op < 1) w.setOpacity(op);
  if (iconGrey && lastRunning === false) w.setIcon(iconGrey);
  w.loadFile(path.join(__dirname, "renderer", "index.html"), { query: { pop: kind } });
  w.once("ready-to-show", () => {
    const area = screen.getDisplayMatching(w.getBounds()).workArea, pb = w.getBounds();
    if (pb.x + pb.width < area.x + 40 || pb.x > area.x + area.width - 40 || pb.y < area.y - 10 || pb.y > area.y + area.height - 40) w.center();
    w.showInactive();
  });
  w.on("close", () => { saveBounds(w, P); if (!quitting) toCore({ id: 0, method: "config.set", params: { key: P.open, value: false } }); });
  w.on("closed", () => { if (pops[kind] === w) delete pops[kind]; });
  toCore({ id: 0, method: "config.set", params: { key: P.open, value: true } });
  winLog(`popped out ${kind}`);
}

/* ───── the window ───── */
function createWindow() {
  const cfg = readConfig();
  win = new BrowserWindow({
    ...savedBounds(MAIN, cfg),
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
  win.once("ready-to-show", () => {
    onScreen(); win.show(); makeTipWin();
    if (cfg.popout_nearby || cfg.style === "hud") popOut("nearby");   // (2.5.0's HUD style is now the pop-out)
    if (cfg.popout_pvp) popOut("pvp");
  });
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
  win.on("close", () => { if (!quitting) saveBounds(); });
  win.on("closed", () => { win = null; tipWin?.destroy(); for (const w of Object.values(pops)) w?.destroy(); });
  for (const ev of ["move", "minimize", "hide"]) win.on(ev, hideTipWin);
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
/** The taskbar icon follows AION 2: in colour while the game runs, grey while it doesn't. */
let iconColour = null, iconGrey = null, lastRunning = null;
function gameIcon(running) {
  if (!win) return;
  if (!iconColour) {
    iconColour = nativeImage.createFromPath(path.join(__dirname, "build", "icon.ico"));
    const { width, height } = iconColour.getSize();
    const px = Buffer.from(iconColour.toBitmap());           // BGRA
    for (let i = 0; i < px.length; i += 4) {
      const y = Math.round(0.114 * px[i] + 0.587 * px[i + 1] + 0.299 * px[i + 2]);
      px[i] = px[i + 1] = px[i + 2] = Math.round(y * 0.85);
    }
    iconGrey = nativeImage.createFromBitmap(px, { width, height });
  }
  lastRunning = running;
  if (!iconColour.isEmpty()) for (const w of allWindows()) w.setIcon(running ? iconColour : iconGrey);
  winLog(`AION 2 ${running ? "running" : "not running"}: ${running ? "gold" : "grey"} icon`);
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

/* ───── item tooltips, in their own window beside the main one (so they never cover the gear) ───── */
let tipWin = null, tipSeq = 0, tipWait = null;
function makeTipWin() {
  tipWin = new BrowserWindow({
    width: 10, height: 10, show: false, frame: false, transparent: true, backgroundColor: "#00000000", resizable: false,
    movable: false, minimizable: false, maximizable: false, focusable: false, skipTaskbar: true, hasShadow: false,
    webPreferences: { preload: path.join(__dirname, "tip-preload.js"), contextIsolation: true, nodeIntegration: false,
      backgroundThrottling: false },
  });
  tipWin.webContents.on("render-process-gone", (_e, d) => { winLog(`tooltip window gone: ${d.reason}`); tipWin?.destroy(); });
  tipWin.setAlwaysOnTop(true, "screen-saver");
  tipWin.setIgnoreMouseEvents(true);
  tipWin.loadFile(path.join(__dirname, "renderer", "tip.html"));
  tipWin.on("closed", () => { tipWin = null; });
}
let tipLogs = 0;                                        // the first few shows, and every problem
function tipLog(msg) { if (tipLogs++ < 5 || !msg.startsWith("shown")) winLog(`tooltip: ${msg}`); }
function hideTipWin() { tipSeq++; if (tipWin?.isVisible()) tipWin.hide(); }
ipcMain.on("tip-size", (_e, m) => { if (tipWait?.seq === m.seq) { tipWait.done(m); tipWait = null; } });
/** Show `html` beside the window, level with screen y. False when neither side has room (the page then shows it
 *  inside the window instead). */
ipcMain.handle("tip", async (_e, action, arg) => {
  if (action === "hide") { hideTipWin(); return null; }
  if (tipWin?.isDestroyed()) tipWin = null;
  if (!tipWin && win) makeTipWin();
  if (!tipWin || !win || tipWin.webContents.isLoading()) return false;
  const seq = ++tipSeq;
  const size = await new Promise((done) => {
    tipWait = { seq, done };
    tipWin.webContents.send("tip", { seq, html: arg.html });
    setTimeout(() => done(null), 400);
  });
  if (seq !== tipSeq) return true;                     // a newer tooltip (or a hide) came in meanwhile
  if (!size || !size.w || !size.h) { tipLog(`no size from the tooltip window (${JSON.stringify(size)})`); return false; }
  const b = win.getBounds(), wa = screen.getDisplayMatching(b).workArea, gap = 6;
  const w = Math.min(size.w, wa.width), h = Math.min(size.h, wa.height);
  let x = b.x + b.width + gap;
  if (x + w > wa.x + wa.width) x = b.x - w - gap;
  if (x < wa.x) { hideTipWin(); tipLog("no room beside the window: shown inside it"); return false; }
  const y = Math.max(wa.y, Math.min(Math.round(arg.y) - 20, wa.y + wa.height - h));
  tipWin.setBounds({ x, y, width: w, height: h });
  if (!tipWin.isVisible()) tipWin.showInactive();
  tipWin.setAlwaysOnTop(false);                         // (re-applied: Windows can silently drop it)
  tipWin.setAlwaysOnTop(true, "screen-saver");
  tipWin.moveTop();
  if (!tipWin.isVisible()) { tipLog("tooltip window didn't show: shown inside the window"); return false; }
  tipLog(`shown at ${x},${y} ${w}x${h}`);
  return true;
});

ipcMain.on("core", (e, msg) => fromWindow(e.sender, msg));
ipcMain.handle("win", async (e, action, arg) => {
  const kind = popKind(e.sender), from = kind ? pops[kind] : win;
  switch (action) {
    case "minimize": winLog(kind ? `${kind} pop-out minimize` : "minimize button"); from?.minimize(); break;
    case "close": if (kind) from.close(); else app.quit(); break;
    case "popOut": popOut(arg); break;
    case "showMain": reveal(); win?.webContents.send("core", { event: "show", data: arg }); break;
    case "alwaysOnTop":
      if (kind) { from.onTop = !!arg; from.setAlwaysOnTop(from.onTop, "screen-saver"); break; }
      pinned = !!arg; pin(pinned, true); winLog(`always on top: ${pinned}`); break;
    case "opacity": {
      const v = Math.max(0.3, Math.min(1, Number(arg) || 1));
      if (kind) { from.setOpacity(v); break; }
      opacity = v; win?.setOpacity(opacity); break;
    }
    case "relaunchAsAdmin": return relaunchAsAdmin();
    case "update": return updater.act(arg);
              // "check" | "download" | "restart" | "state"
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
  winLog(`──── Shugo Tracker ${app.getVersion()} started${process.argv.includes("--after-update") ? " after an update" : ""}`);
  startCore();
  createWindow();
  const cfg = readConfig();
  if (!DEMO) updater.start(cfg.update_check_s ?? (cfg.auto_update === false ? 0 : 1800));
});

app.on("before-quit", () => {
  if (quitting) return;
  saveBounds();                                        // first: the core is told to quit right after
  for (const [k, w] of Object.entries(pops)) saveBounds(w, POPS[k]);
  quitting = true;
  toCore({ method: "quit" });
  setTimeout(() => core?.kill(), 1500);
  updater.onQuit();
});
app.on("window-all-closed", () => app.quit());
