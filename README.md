# Shugo Tracker

A fast, modern **AION 2 (Global) character search**. Type a name and get every matching character across
all Global regions — class, level, server, faction, **gear score** and **combat power** — and open a full
profile in the app.

- Searches NA East, NA West, Europe, Latin America and Asia at the same time.
- Results appear instantly as skeleton cards; gear score and combat power fill in for the cards you can see,
  and more results load as you scroll — so even a common name with thousands of matches stays smooth.
- Each character's **<Legion>** is shown next to their name.
- Click any character for a full profile: gear, skills, Daevanion boards, stats, cosmetics and titles.
- Star characters to keep them in **★ Favorites**.
- Toggle region and faction filters on and off instantly. Pin the window on top of the game.
- Updates itself from this repo's releases.

*Shugo Tracker is an independent fan tool. It reads NCSOFT's public AION 2 character data and is not made by
or affiliated with NCSOFT or Shugo.GG.*

## Install & run

1. Download **`ShugoTracker.exe`** from the latest
   [release](https://github.com/CynicaGaming/Shugo-Tracker/releases/latest) and put it in its own folder.
2. Run it. SmartScreen may warn the first time because the exe isn't code-signed: *More info → Run anyway*.
   No administrator rights or extra installs are needed.

`config.json`, `favorites.json`, the cache and `shugo-tracker.log` are kept in `%APPDATA%\ShugoTracker`, so they
survive updates and moving the exe (older versions kept them next to the exe; they're moved over on first start).
`ShugoTracker.exe --demo` shows the window with made-up characters (no network).

## The overlay

Shugo Tracker is a frameless, always-on-top window meant to sit over the game (play in **borderless
windowed** mode):

| | |
|---|---|
| drag the title bar | move it |
| ◢ (bottom-right corner) | resize it |
| — | collapse to a small Shugo bubble; drag the bubble anywhere, click it to expand |
| ⚙ | settings |
| ✕ | quit (with *Close to tray* on in ⚙: hide; a tray icon appears until you bring it back) |

Starting it again while it's running (even hidden) brings the running copy forward. When an update is
waiting, the ⚙ turns gold.

### Settings (⚙)

| | |
|---|---|
| Window | opacity (100% by default); always on top; close to tray |
| Startup & updates | start with Windows; check for updates automatically; check now |
| Data | cache size and Clear; open the folder with settings, favorites and cache |

Everything is saved immediately.

## Using it

| | |
|---|---|
| type a name, press Enter | search (it also searches by itself after you pause typing) |
| Region / Faction / Class chips | click to filter, click again to remove; nothing selected = everything; **Clear** resets all filters |
| Lv [min] – [max] | level range; fill in either or both |
| click a card | open the character's profile |
| ☆ on a card or in a profile | add or remove a favorite (see the **★ Favorites** tab) |
| right-click a card | profile / favorite / copy name / refresh |
| 📌 | keep the window above other windows |

The profile has tabs for **Gear** (equipment, accessories and Arcana with grade and enchant level),
**Skills** (Active, Passive and Stigma, equipped first), **Daevanion** (board progress), **Stats** (primary and
deity stats with their effects), **Cosmetics** (wings, wing appearance, pet, outfit) and **Titles**, plus the
character's legion. Per-item stat rolls aren't part of NCSOFT's public
data, so items show name, grade and enchant level.

Search matches anywhere in the name (“luna” also finds “Aluna”); exact matches and higher levels come first.

## Where the data comes from

Shugo Tracker reads NCSOFT's public AION 2 endpoints directly:

- **Search:** `api-search.plaync.com/aion2global/search/v2/character` — one request per region, 30 results a page.
  Class, a single faction and an exact level are filtered by NCSOFT (`pcId`, `race`, `level`); a level range is
  filtered in the app.
- **Details:** `aion2.plaync.com/api/character/info` — combat power, item level (gear score), stats, titles,
  Daevanion boards, legion.
- **Gear:** `aion2.plaync.com/api/character/equipment` — equipment, cosmetics, wings, pet and skills
  (only requested when you open a profile).

Details are only requested for cards on screen, newest scroll position first, by 4 parallel workers sharing a
hard limit of 6 requests in any one second (halved automatically if the server says to slow down); a
search's five region requests go out together. Opening a profile reuses the info a card has just loaded, so
only the gear is fetched. Starting a new search cancels the old one's pending requests.

Caching (in the data folder, `character_cache.json` and `cache/`):

- card numbers are kept for 7 days and shown instantly; if older than 30 minutes they refresh quietly;
- profiles are kept for 7 days and shown instantly; if older than 10 minutes they refresh quietly;
- portraits (1 day) and game icons (30 days) are stored on disk;
- the same search within 15 minutes is answered from memory;
- a profile (gear, skills, …) is only fetched when you open it.

Delete the `cache` folder and `character_cache.json` at any time to start fresh.

## Updates

The **Check for updates** button is in ⚙ Settings (the ⚙ turns gold when an update is waiting):

| button shows | meaning / what clicking does |
|---|---|
| Check for updates | asks GitHub for the latest release |
| ✓ Up to date | you have the newest version (goes back to *Check for updates* after a few seconds) |
| ⬇ Download v1.x.y | a newer version exists — click to download it (shows progress) |
| Restart | downloaded and checksum-verified — click to switch to the new version |

The app also checks quietly at start-up and every 6 hours, so the button may already say
**Download** when you open it; nothing is downloaded until you click. If you quit with an update
downloaded, it's installed on exit. `config.json`, favorites and the cache are kept. Set
`"auto_update": false` to turn off the automatic checks (the button still works).

Builds made with `build_exe.bat` show **✓ Dev build** and are never replaced; running from source,
the button opens the release page instead.

## Development & publishing

The repo holds the source; the exe is only built when you publish.

- **Every push / PR** runs the tests on Windows (`.github/workflows/ci.yml`), takes screenshots, and builds a
  throwaway exe to check that favorites survive a restart. Nothing is published.
- **To publish a version**, either
  - GitHub → **Actions → Publish release → Run workflow**, enter a version such as `1.2.0`, or
  - `git tag v1.2.0 && git push origin v1.2.0`.

  `.github/workflows/release.yml` runs the tests, stamps the version into `shugotracker/_version.py`, builds
  `ShugoTracker.exe` with PyInstaller, and publishes a release with the exe, its `.sha256` and
  `ShugoTracker-windows.zip`. Every installed copy then updates itself. Versions must go up
  (`MAJOR.MINOR.PATCH`); the updater ignores anything not newer than what's running.

Working locally:

- `run.bat` — run from source (sets up a venv, runs `python -m shugotracker.app`).
- `python -m shugotracker.app --search-cli NAME` — search from a terminal.
- `build_exe.bat` — build `dist\ShugoTracker.exe` on your PC (version shows as `0.0.0-dev`; dev builds never
  auto-update).
- `python -m unittest discover -s tests -t .` — tests.

## config.json

| key | default | meaning |
|---|---|---|
| `regions` / `factions` | `[]` / `[]` | last filters used (empty = all) |
| `always_on_top` | `true` | pin the window above other windows |
| `auto_update` | `true` | check for new releases at start-up and every 6 hours |
| `update_repo` | `"CynicaGaming/Shugo-Tracker"` | GitHub repo the updater follows |

| `nearby_enabled` | `false` | Nearby players is on (opt-in, see below) |
| `my_server` | `""` | Nearby: your server until the game reveals it: `"nae-siel"`, `"eu-ludra"` or `1101` |
| `opcodes` | | Nearby: packet opcodes — see *After a game patch* |

## Nearby players (opt-in, beta)

The **◉ Nearby** tab lists the players around your character, split into **Enemies** and **Allies**, with the
same cards (gear score, combat power, profile on click) as search. It is off until you turn it on in the tab
(or in ⚙ Settings → *Nearby players*), and it can be turned off there at any time.

It needs **[Npcap](https://npcap.com/#download)** (free; the default install options are fine). Shugo Tracker
then reads the game's own downstream traffic on this PC: only AION2.exe's connections, found in the Windows
connection table. It never sends anything to the game or changes anything; the only network requests are the
normal NCSOFT character searches (one per player on screen, inside the app's 6-per-second limit). Reading
game traffic may be against AION 2's terms of service — use it at your own risk.

| | |
|---|---|
| red / green edge on a card | enemy / ally |
| Faction / Class / Level | the usual filters apply here too (Faction = Elyos or Asmodian) |
| a card still shimmering | the game showed the player; NCSOFT hasn't identified them yet |

### Who shows up, and where

**Everyone in render range.** Players are added when the game sends their spawn record (they come into view,
or you load a map), removed when it sends the record that they left view, and the list is reset when you load
a new map (the game re-sends everyone around you). A player whose leave record was missed is dropped after
15 minutes without activity.

**Enemy / ally.** Since the October 2026 client, a player's spawn record carries their faction and exact
class directly, so invaders and locals are told apart the moment they appear (no lookup needed). Otherwise:
AION 2 Global server ids encode faction (`race × 1000 + region × 100 + n`; race 1 = Elyos,
2 = Asmodian), so a player on the other faction's server is an enemy and one on yours an ally. Someone
fighting you counts as an enemy until their server is known. Your own character and server come from the
record sent when you log in or load a map; if you turn Nearby on mid-session, load a map once (or set
`"my_server"`).

Players are listed as soon as the game sends their spawn record, and every one is identified in the
background (cards on screen first): one NCSOFT search for the exact name and class in your region, which gives
their real server and faction. Names are only unique per server, so between namesakes the app uses, in order,
the server named by the game, ignores level-1 characters (mostly reserved names), prefers servers already seen
around you, then your faction, then the highest level. Your region and character are remembered.

### Troubleshooting

From source, `python -m shugotracker.app --replay-bin FILE` decodes a Nearby recording (made with
`NearbyService.start_recording`) and prints every record found — the way to check the decoder after a patch.

### After a game patch

Patches sometimes renumber opcodes (the June 2026 patch shifted the `xx 36` family by one). If names stop
appearing or players never leave the list, the `opcodes` block in `config.json` needs updating.

The wire layout comes from the community DPS-meter projects (A2Tools-DPS-Meter, AIon2-Dps-Meter,
aion2-dps-meter, Aion2DPSMeter — all GPL-3.0). The despawn and map-load records are the least battle-tested
part: those meters use them for NPCs and world objects; using them for players is new here.

### Limitations

- Player names only arrive with spawn records. Someone already in range when Nearby starts stays invisible
  until they re-enter view or you load a map.
- NCSOFT's search only knows characters it lists; a brand-new character may stay unidentified for a while.

## Credits & licence

The packet layouts were reverse-engineered and published by the open-source AION 2 meters —
[A2Tools-DPS-Meter](https://github.com/taengu/A2Tools-DPS-Meter),
[AIon2-Dps-Meter](https://github.com/Kuroukihime/AIon2-Dps-Meter),
[aion2-dps-meter](https://github.com/cyberbadger6969/aion2-dps-meter),
[Aion2DPSMeter](https://github.com/domel1998/Aion2DPSMeter) and
[aion2-combat-meter](https://github.com/mgauna-ar/aion2-combat-meter). The server table comes from A2Tools'
data. This is an independent Python implementation, released under **GPL-3.0** (see `LICENSE`).
Character data from NCSOFT's public AION 2 site. Not affiliated with NCSOFT or Shugo.GG.
