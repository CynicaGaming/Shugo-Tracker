// The only bridge between the page and the rest of the app: messages to / from the Python core, window controls.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("shugo", {
  send: (msg) => ipcRenderer.send("core", msg),
  onMessage: (fn) => ipcRenderer.on("core", (_e, msg) => fn(msg)),
  win: {
    minimize: () => ipcRenderer.invoke("win", "minimize"),
    close: () => ipcRenderer.invoke("win", "close"),
    setAlwaysOnTop: (on) => ipcRenderer.invoke("win", "alwaysOnTop", on),
    setOpacity: (v) => ipcRenderer.invoke("win", "opacity", v),
    relaunchAsAdmin: () => ipcRenderer.invoke("win", "relaunchAsAdmin"),
    popOut: (kind) => ipcRenderer.invoke("win", "popOut", kind),
    pickSound: () => ipcRenderer.invoke("win", "pickSound"),
    lock: (on) => ipcRenderer.invoke("win", "lock", on),
    clickThrough: (state) => ipcRenderer.invoke("win", "clickThrough", state),
    popState: () => ipcRenderer.invoke("win", "popState"),
    popClose: (kind) => ipcRenderer.invoke("win", "popClose", kind),
    popClickThroughOff: (kind) => ipcRenderer.invoke("win", "popClickThroughOff", kind),
    readSound: (file) => ipcRenderer.invoke("win", "readSound", file),
    showMain: (what) => ipcRenderer.invoke("win", "showMain", what),
    update: (action) => ipcRenderer.invoke("win", "update", action),
    onUpdate: (fn) => ipcRenderer.on("update", (_e, s) => fn(s)),
  },
  tip: {                                                // item tooltips beside the window
    show: (html, y) => ipcRenderer.invoke("tip", "show", { html, y }),
    hide: () => ipcRenderer.invoke("tip", "hide"),
  },
});
