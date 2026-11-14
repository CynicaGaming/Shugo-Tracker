// CI: start the real Electron app (demo data) and save screenshots of every screen into ../shots.
const { _electron: electron } = require("playwright");
const path = require("path");
const fs = require("fs");

(async () => {
  const out = path.join(__dirname, "..", "..", "shots");
  fs.mkdirSync(out, { recursive: true });
  const app = await electron.launch({ args: [path.join(__dirname, ".."), "--demo"], cwd: path.join(__dirname, "..") });
  const page = await app.firstWindow();
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
  await page.hover(".slot");
  await shot("profile-gear-tip", 500);
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
  fs.writeFileSync(path.join(out, "log.txt"), log.join("\n") || "OK");
  await app.close();
})().catch((e) => { console.error(e); process.exit(1); });
