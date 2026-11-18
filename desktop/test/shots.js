// CI: start the real Electron app (demo data) and save screenshots of every screen into ../shots.
const { _electron: electron } = require("playwright");
const path = require("path");
const fs = require("fs");

(async () => {
  const out = path.join(__dirname, "..", "..", "shots");
  fs.mkdirSync(out, { recursive: true });
  const app = await electron.launch({ args: [path.join(__dirname, ".."), "--demo"], cwd: path.join(__dirname, "..") });
  await app.firstWindow();
  let page;                                                // the main window (not the tooltip window)
  for (let i = 0; i < 100 && !page; i++) {
    page = app.windows().find((w) => w.url().endsWith("index.html"));
    if (!page) await new Promise((r) => setTimeout(r, 100));
  }
  const log = [];
  page.on("pageerror", (e) => log.push(`pageerror: ${e}`));
  page.on("console", (m) => { if (m.type() === "error") log.push(`console: ${m.text()}`); });
  await page.setViewportSize({ width: 600, height: 760 }).catch(() => {});
  const shot = async (name, wait = 600) => { await page.waitForTimeout(wait); await page.screenshot({ path: path.join(out, `${name}.png`) }); };
  await page.waitForTimeout(3000);
  await page.fill(".searchbox input", "Luna");
  await page.keyboard.press("Enter");
  await shot("search", 3500);
  await page.click(".row", { button: "right" });
  await shot("row-menu", 400);
  await page.keyboard.press("Escape");
  await page.click(".row");
  await shot("profile-loading", 800);
  await page.waitForSelector(".pbody .gear", { timeout: 20000 });
  await shot("profile-gear", 300);
  await page.evaluate(() => { window.tipsInWindow = true; });   // (tooltips beside the window aren't in the page shot)
  await page.hover(".slot");
  await shot("profile-gear-tip", 500);
  // the real thing: the tooltip in its own window beside the main one
  await page.mouse.move(5, 5);
  await page.evaluate(() => { window.tipsInWindow = false; });
  const bounds = await app.evaluate(({ BrowserWindow }) => { const w = BrowserWindow.getAllWindows().sort((a, b) => a.id - b.id)[0]; const b = w.getBounds(); w.setBounds({ ...b, x: 0 }); return b; });
  await page.waitForTimeout(300);                          // (room on the right for it)
  await page.hover(".slot");
  await page.waitForTimeout(800);
  const tipPage = app.windows().find((w) => w.url().endsWith("tip.html"));
  const where = await app.evaluate(({ BrowserWindow }) => {
    const [main, tip] = BrowserWindow.getAllWindows().sort((a, b) => a.id - b.id);
    return { main: main.getBounds(), tip: tip.getBounds(), shown: tip.isVisible() };
  });
  const beside = where.tip.x >= where.main.x + where.main.width || where.tip.x + where.tip.width <= where.main.x;
  if (!tipPage || !where.shown || !beside || where.tip.width < 200) log.push(`tooltip window: ${JSON.stringify(where)}`);
  else await tipPage.screenshot({ path: path.join(out, "profile-gear-tip-window.png") });
  await page.mouse.move(5, 5);
  await page.waitForTimeout(300);
  if (await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().sort((a, b) => a.id - b.id)[1].isVisible()))
    log.push("tooltip window stayed up after the mouse left");
  await app.evaluate(({ BrowserWindow }, b) => BrowserWindow.getAllWindows().sort((a, c) => a.id - c.id)[0].setBounds(b), bounds);
  await page.evaluate(() => { window.tipsInWindow = true; });
  for (const [i, name] of [[2, "skills"], [3, "daevanion"], [4, "stats"], [5, "cosmetics"], [6, "titles"]]) {
    await page.click(`.ptabs .tab:nth-child(${i})`);
    await shot(`profile-${name}`, 1200);
  }
  await page.click(".ptabs .tab:nth-child(3)");
  await page.hover(".node.open:not(.start)").catch(() => {});
  await shot("profile-daevanion-node", 500);
  await page.click(".tab.back");
  await page.click(".mebtn");
  await shot("me-menu", 400);
  await page.click(".menu .item:last-child");
  await shot("settings", 800);
  await page.click(".tab.back");
  await page.click(".tabs .tab:has-text('PVP')");                 // PVP Log (demo fights)
  await shot("pvp", 800);
  await page.click(".pvprow");
  await shot("pvp-foe", 800);
  // Pop Out Nearby: right-click the Nearby tab; a slim always-on-top window of its own
  await page.click(".tab.back");
  await page.evaluate(() => window.__app.enableNearby());
  await page.waitForTimeout(1500);
  await page.click(".tabs .tab:has-text('Nearby')", { button: "right" });
  await page.click(".menu .item:has-text('Pop Out Nearby')");
  let pop;
  for (let i = 0; i < 60 && !pop; i++) {
    pop = app.windows().find((w) => w.url().includes("pop=nearby"));
    if (!pop) await page.waitForTimeout(100);
  }
  if (!pop) log.push("pop out: no window");
  else {
    await pop.waitForTimeout(3500);
    await pop.screenshot({ path: path.join(out, "popout.png") });
    const sz = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().map((w) => [w.getTitle(), ...w.getContentSize()]));
    if (!sz.some(([t, w]) => t.includes("Nearby") && w <= 320)) log.push(`pop out: sizes ${JSON.stringify(sz)}`);
    await pop.click(".hudrow").catch(() => log.push("pop out: no rows"));
    await page.waitForSelector(".pbody", { timeout: 5000 }).catch(() => log.push("pop out: the profile didn't open in the main window"));
    await shot("popout-profile", 800);
  }
  fs.writeFileSync(path.join(out, "log.txt"), log.join("\n") || "OK");
  await app.close();
})().catch((e) => { console.error(e); process.exit(1); });
