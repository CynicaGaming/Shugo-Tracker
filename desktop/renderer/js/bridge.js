// Talks to the Python core: through Electron's preload bridge in the app, or the dev server in a browser preview.

const listeners = {};
let seq = 0;
const pending = new Map();

function dispatch(msg) {
  if (msg.id != null && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(msg.error)) : resolve(msg.result);
  } else if (msg.event) {
    (listeners[msg.event] || []).forEach((fn) => fn(msg.data));
  }
}

// The Android app (android/…/MainActivity.kt): requests go out through AndroidCore.send, answers and events come
// back through window.__shugoIn. Shaped like the desktop bridge, so the rest of the page doesn't care.
export const MOBILE = !!window.AndroidCore || new URLSearchParams(location.search).has("mobile");
if (window.AndroidCore && !window.shugo) {
  const subs = [];
  window.__shugoIn = (line) => { const m = JSON.parse(line); subs.forEach((fn) => fn(m)); };
  window.shugo = { send: (msg) => window.AndroidCore.send(JSON.stringify(msg)), onMessage: (fn) => subs.push(fn) };
}
if (MOBILE) document.documentElement.classList.add("mobile");
const native = window.shugo;          // set by desktop/preload.js (or above, on Android)
if (native) native.onMessage(dispatch);
else {
  const es = new EventSource("/events");
  es.onmessage = (e) => dispatch(JSON.parse(e.data));
}

export function call(method, params = {}) {
  const id = ++seq;
  const msg = { id, method, params };
  if (native) {
    return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); native.send(msg); });
  }
  return fetch("/rpc", { method: "POST", body: JSON.stringify(msg) }).then((r) => r.json()).then((m) => {
    if (m.error) throw new Error(m.error);
    return m.result;
  });
}

export function on(event, fn) { (listeners[event] ||= []).push(fn); return () => off(event, fn); }
export function off(event, fn) { listeners[event] = (listeners[event] || []).filter((f) => f !== fn); }

/** Window controls (Electron only; no-ops in a browser preview). On Android, updates go through the core. */
export const win = native?.win || {
  minimize() {}, close() {}, setAlwaysOnTop() {}, popOut() {}, showMain() {}, pickSound: async () => null, lock() {}, clickThrough() {}, popState: async () => [], popClose() {}, popClickThroughOff() {}, readSound: async () => null, setOpacity() {}, relaunchAsAdmin() {}, update: async () => ({ state: "dev" }), onUpdate() {},
  ...(window.AndroidCore ? { update: (action) => call("app.update", { action }), onUpdate: (fn) => on("update", fn) } : {}),
};
