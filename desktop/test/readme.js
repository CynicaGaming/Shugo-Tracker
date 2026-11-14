// CI: README screenshots. Demo data plus one real character (Cynica, live from NCSOFT) so items and skills
// show their real icons. Saved as ../../shots/show-*.png; tools/readme_images.py frames them for docs/images.
const { _electron: electron } = require("playwright");
const path = require("path");
const fs = require("fs");

const W = 560, H = 720;

(async () => {
  const out = path.join(__dirname, "..", "..", "shots");
  fs.mkdirSync(out, { recursive: true });
  const app = await electron.launch({ args: [path.join(__dirname, ".."), "--showcase=Cynica@Kaisinel=Cynica"],
    cwd: path.join(__dirname, "..") });
  const page = await app.firstWindow();
  await app.evaluate(({ BrowserWindow }, [w, h]) => BrowserWindow.getAllWindows()[0].setContentSize(w, h), [W, H]);
  const shot = async (name, wait = 600) => { await page.waitForTimeout(wait); await page.screenshot({ path: path.join(out, `show-${name}.png`) }); };
  const core = (method, params) => page.evaluate(async ([m, p]) => {
    const b = await import(new URL("js/bridge.js", location.href).href);
    return b.call(m, p);
  }, [method, params]);
  const tab = (i) => page.click(`.tabs .tab:nth-child(${i})`);
  await page.waitForTimeout(3000);

  // search
  await page.fill(".searchbox input", "Cynica");
  await page.keyboard.press("Enter");
  await shot("search", 5000);
  await page.click(".filters .chip:has-text('More')");
  await shot("filters", 600);
  await page.click(".filters .chip:has-text('Less')");
  await page.click(".thead", { button: "right" });
  await shot("columns-menu", 400);
  await page.keyboard.press("Escape");

  // favorites: star a few
  for (const i of [2, 4, 5, 7]) await page.click(`.row:nth-child(${i}) .c.star`).catch(() => {});
  await tab(2);
  await shot("favorites", 800);
  await tab(1);

  // profile
  await page.click(".row");
  await page.waitForSelector(".pbody .gear", { timeout: 30000 });
  await shot("profile-gear", 800);
  await page.hover(".slot");
  await shot("profile-gear-tip", 900);
  await page.click(".ptabs .tab:nth-child(2)");
  await page.hover(".stile").catch(() => {});
  await shot("profile-skills-tip", 900);
  await page.click(".ptabs .tab:nth-child(3)");
  await shot("profile-daevanion", 1500);
  await page.click(".tab.back");

  // Nearby and Recent (demo players)
  await core("nearby.enable", { on: true });
  await page.waitForTimeout(6000);
  await tab(3);
  await shot("nearby", 1500);
  await tab(4);
  await shot("recent", 1000);
  await app.close();
})().catch((e) => { console.error(e); process.exit(1); });
