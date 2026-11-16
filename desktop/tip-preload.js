// The tooltip window's bridge: receives a tooltip's markup and reports its size back.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("tipwin", {
  onShow: (fn) => ipcRenderer.on("tip", (_e, m) => fn(m)),
  size: (m) => ipcRenderer.send("tip-size", m),
});
