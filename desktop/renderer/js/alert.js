// Enemy alert: a sound when an enemy shows up on Nearby, at most once per cooldown. The built-in chime is made
// on the spot (no file); your own sound lives in data\sounds and is played at the volume you set.
import { win } from "./bridge.js";

let ctx = null, custom = { file: null, buf: null }, last = 0, seen = new Set(), primed = false;
const audio = () => (ctx ||= new AudioContext());

async function customBuffer(file) {
  if (custom.file === file && custom.buf) return custom.buf;
  const bytes = await win.readSound(file);
  if (!bytes) return null;
  const ab = bytes.buffer ? bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) : bytes;
  custom = { file, buf: await audio().decodeAudioData(ab) };
  return custom.buf;
}

function chime(volume) {
  const a = audio(), t = a.currentTime;
  for (const [f, at] of [[880, 0], [1318.5, 0.12]]) {             // A5 then E6: two soft bell notes
    const o = a.createOscillator(), g = a.createGain();
    o.type = "sine"; o.frequency.value = f;
    g.gain.setValueAtTime(0.0001, t + at);
    g.gain.exponentialRampToValueAtTime(0.35 * volume, t + at + 0.015);
    g.gain.exponentialRampToValueAtTime(0.0001, t + at + 0.5);
    o.connect(g).connect(a.destination);
    o.start(t + at); o.stop(t + at + 0.55);
  }
}

/** Play the alert now (Settings → Test, or an enemy). */
export async function playAlert(cfg) {
  const volume = Math.max(0, Math.min(1, cfg.alert_volume ?? 0.8));
  try {
    if (audio().state === "suspended") await audio().resume();
    const buf = cfg.alert_sound ? await customBuffer(cfg.alert_sound) : null;
    if (!buf) { chime(volume); return; }
    const src = audio().createBufferSource(), g = audio().createGain();
    src.buffer = buf; g.gain.value = volume;
    src.connect(g).connect(audio().destination);
    src.start();
  } catch { chime(volume); }                                       // a file it can't play: the chime instead
}

/** Nearby changed: a sound if an enemy is new since last time (and the cooldown has passed). */
export function nearbyChanged(nearby, cfg) {
  const enemies = new Set((nearby.enabled ? nearby.rows : []).filter((r) => r.side === "enemy").map((r) => r.char.name));
  const fresh = [...enemies].some((n) => !seen.has(n));
  seen = enemies;
  if (!primed) { primed = true; return; }                          // (the list the window opened with isn't news)
  if (!fresh || !cfg.alert_enemy) return;
  const now = Date.now();
  if (now - last < (cfg.alert_cooldown_s ?? 30) * 1000) return;
  last = now;
  playAlert(cfg);
}
