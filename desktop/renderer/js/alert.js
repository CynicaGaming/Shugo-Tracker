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

/** The built-in sounds, made on the spot: [label, notes: [frequency Hz, start s, length s, wave, slide-to Hz]]. */
export const SOUNDS = {
  chime: ["Chime", [[880, 0, 0.5, "sine"], [1318.5, 0.12, 0.5, "sine"]]],
  ping: ["Ping", [[1760, 0, 0.35, "sine"]]],
  bell: ["Bell", [[1046.5, 0, 0.9, "sine"], [2093, 0, 0.6, "sine"], [783.99, 0.18, 0.9, "sine"]]],
  beeps: ["Beeps", [[1200, 0, 0.09, "square"], [1200, 0.14, 0.09, "square"], [1200, 0.28, 0.09, "square"]]],
  alarm: ["Alarm", [[600, 0, 0.22, "sawtooth", 1100], [600, 0.26, 0.22, "sawtooth", 1100]]],
  drum: ["War Drum", [[110, 0, 0.35, "sine", 55], [110, 0.22, 0.35, "sine", 55]]],
};
export const soundKind = (cfg) => cfg.alert_sound_kind || (cfg.alert_sound ? "custom" : "chime");

function synth(kind, volume) {
  const a = audio(), t = a.currentTime;
  const loud = { square: 0.12, sawtooth: 0.14 };
  for (const [f, at, len, wave, to] of (SOUNDS[kind] || SOUNDS.chime)[1]) {
    const o = a.createOscillator(), g = a.createGain();
    o.type = wave; o.frequency.setValueAtTime(f, t + at);
    if (to) o.frequency.exponentialRampToValueAtTime(to, t + at + len);
    const peak = (loud[wave] || 0.35) * volume;
    g.gain.setValueAtTime(0.0001, t + at);
    g.gain.exponentialRampToValueAtTime(Math.max(peak, 0.0002), t + at + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t + at + len);
    o.connect(g).connect(a.destination);
    o.start(t + at); o.stop(t + at + len + 0.05);
  }
}
const chime = (volume) => synth("chime", volume);

/** Play the alert now (Settings → Test, or an enemy). */
export async function playAlert(cfg) {
  const volume = Math.max(0, Math.min(1, cfg.alert_volume ?? 0.8));
  try {
    if (audio().state === "suspended") await audio().resume();
    const kind = soundKind(cfg);
    const buf = kind === "custom" && cfg.alert_sound ? await customBuffer(cfg.alert_sound) : null;
    if (!buf) { synth(kind === "custom" ? "chime" : kind, volume); return; }
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
