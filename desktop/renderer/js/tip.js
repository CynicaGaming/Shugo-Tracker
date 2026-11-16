// The tooltip window: shows the markup the main page sends, then reports how big it is so the window fits it.
const root = document.getElementById("root");
window.tipwin.onShow(({ seq, html }) => {
  root.innerHTML = html;
  // measured right away (layout is synchronous): a hidden window may never get an animation frame
  const r = root.getBoundingClientRect();
  window.tipwin.size({ seq, w: Math.ceil(r.width), h: Math.ceil(r.height) });
});
