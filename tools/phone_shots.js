// The README's phone screenshots: the Android app's screens at phone size, from the browser preview with live data.
//   python -m shugotracker.devserver --port 8791      (then)      node tools/phone_shots.js <out folder>
const { chromium, devices } = require('playwright');
const OUT = process.argv[2] || 'phone';
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ ...devices['Pixel 7'], deviceScaleFactor: 3 });
  p.on('pageerror', e => console.log('ERR', e.message));
  const shot = (n) => p.screenshot({ path: `${OUT}/${n}.png` });
  await p.goto('http://127.0.0.1:8791/?mobile&q=Cynica', { waitUntil: 'networkidle' });
  await p.waitForTimeout(9000);
  await shot('search');
  const ok = await p.evaluate(() => { const a = window.__app; const c = a.S.results.find((c) => c.name === 'Cynica' && c.server_name === 'Kaisinel' && c.portrait) || a.S.results[0]; a.openProfile(c); return c.server_name; });
  console.log('opened', ok);
  await p.waitForSelector('.gear .slot', { timeout: 60000 }); await p.waitForTimeout(4000);
  await shot('gear');
  await p.locator('.gear .slot').nth(0).tap(); await p.waitForTimeout(1500);
  await shot('gear-tip');
  await p.locator('.gear .slot').nth(0).tap(); await p.waitForTimeout(300);
  for (const t of ['Stats', 'Skills', 'Daevanion']) { await p.locator('.ptabs >> text=' + t).first().tap(); await p.waitForTimeout(2500); await shot(t.toLowerCase()); }
  await b.close();
})();
