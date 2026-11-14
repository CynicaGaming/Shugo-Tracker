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
    openFolder: () => ipcRenderer.invoke("win", "openFolder"),
    openExternal: (url) => ipcRenderer.invoke("win", "openExternal", url),
    relaunchAsAdmin: () => ipcRenderer.invoke("win", "relaunchAsAdmin"),
    update: (action) => ipcRenderer.invoke("win", "update", action),
    onUpdate: (fn) => ipcRenderer.on("update", (_e, s) => fn(s)),
  },
});
