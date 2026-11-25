// About: the app and its version, where it lives on GitHub, who it relies on, and the fine print.
import { MOBILE } from "./bridge.js";
import { ICONS, LOGO, h, icon } from "./dom.js";

const REPO = "https://github.com/CynicaGaming/Shugo-Tracker";

/** Links open in your browser (the desktop app hands new windows to it; the phone app has its own bridge). */
export function openLink(url) {
  if (window.AndroidCore?.openUrl) window.AndroidCore.openUrl(url);
  else window.open(url, "_blank", "noopener");
}

export class AboutView {
  constructor(app) {
    this.app = app;
    this.el = h("div.scroll.about");
    this.build();
  }

  build() {
    const { S } = this.app;
    const app = S.update?.current || S.version;
    const link = (label, sub, url) => h("button.setting.alink", { onClick: () => openLink(url) },
      h("div.grow", {}, label, sub ? h("div.sub", {}, sub) : null), h("span.ext", { html: ICONS.external }));
    const row = (label, value) => h("div.setting", {}, h("div.grow", {}, label), h("span.val", {}, value));

    this.el.append(
      h("div.ahero", {}, h("span.alogo", { html: LOGO }),
        h("div.at", {}, "Shugo Tracker"),
        h("div.as", {}, "Every AION 2 player's gear, power and build, a glance away.")),
      h("div.bar", {}, "Version"),
      row("Shugo Tracker", app),
      ...(S.version && S.version !== app ? [row("Core", S.version)] : []),
      row("License", "GPL-3.0"),
      h("div.bar", {}, "Links"),
      link("GitHub", "Source code, downloads and every release", REPO),
      link("What's New", `Release notes for ${app}`, `${REPO}/releases/tag/v${app}`),
      link("Report a Problem", "Open an issue on GitHub", `${REPO}/issues`),
      h("div.bar", {}, "Credits"),
      link("NCSOFT", "Character data from the official AION 2 website", "https://aion2.plaync.com"),
      h("div.bar", {}, "Disclaimers"),
      h("div.legal.left", {},
        h("p", {}, "Shugo Tracker is a fan-made tool and isn't affiliated with or endorsed by NCSOFT. AION and AION 2 ",
          "are trademarks of NCSOFT Corporation; game names, text and images belong to NCSOFT."),
        MOBILE ? null : h("p", {}, "Nearby reads the game's network traffic on your PC. It never sends, changes or injects anything, ",
          "but reading game traffic may still be against AION 2's Terms of Service. Use it at your own risk; Shugo Tracker ",
          "isn't responsible for any action taken against your account."),
        h("p", {}, "No account, no sign-in, no tracking: Shugo Tracker sends nothing about you anywhere. It only asks NCSOFT's ",
          "public website for the characters you look up, and GitHub for updates."),
        h("p", {}, "Free software under the GNU General Public License v3.0, provided as is, without warranty of any kind.")),
    );
  }
}
