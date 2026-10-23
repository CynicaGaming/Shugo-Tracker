# Shugo Tracker

A fast, modern **AION 2 (Global) character search**. Type a name and get every matching character across
all Global regions — class, level, server, faction, **gear score** and **combat power** — with one click to
open their [Shugo.GG](https://shugo.gg) profile.

- Searches NA East, NA West, Europe, Latin America and Asia at the same time.
- Results appear instantly as skeleton cards; gear score and combat power fill in for the cards you can see,
  and more results load as you scroll — so even a common name with thousands of matches stays smooth.
- Each character's **<Legion>** is shown next to their name.
- Click any character for a full profile: gear, skills, Daevanion boards, stats, cosmetics and titles.
- Star characters to keep them in **★ Favorites**.
- Toggle region and faction filters on and off instantly. Pin the window on top of the game.
- Updates itself from this repo's releases.

*Shugo Tracker is an independent fan tool. It reads the same public NCSOFT character endpoints Shugo.GG uses
and links to Shugo.GG profiles, but it is not made by or affiliated with Shugo.GG or NCSOFT.*

## Install & run

1. Download **`ShugoTracker.exe`** from the latest
   [release](https://github.com/CynicaGaming/Shugo-Tracker/releases/latest) and put it in its own folder.
2. Run it. SmartScreen may warn the first time because the exe isn't code-signed: *More info → Run anyway*.
   No administrator rights or extra installs are needed.

`config.json`, `favorites.json`, `character_cache.json` and `shugo-tracker.log` are kept next to the exe.
`ShugoTracker.exe --demo` shows the window with made-up characters (no network).

## Using it

| | |
|---|---|
| type a name, press Enter | search (it also searches by itself after you pause typing) |
| region / faction chips | click to filter, click again to remove; nothing selected = everything |
| click a card | open the character's profile |
| ☆ on a card or in a profile | add / remove a favorite (see the **★ Favorites** tab) |
| right-click a card | profile / favorite / open on Shugo.GG / copy name / refresh |
| 📌 | keep the window above the game (play in borderless windowed) |

The profile has tabs for **Gear** (equipment, accessories and Arcana with grade and enchant level),
**Skills** (Active, Passive and DP, equipped first), **Daevanion** (board progress), **Stats** (primary and
deity stats with their effects), **Cosmetics** (wings, wing appearance, pet, outfit) and **Titles**, plus the
character's legion and a link to their Shugo.GG page. Per-item stat rolls aren't part of NCSOFT's public
data, so items show name, grade and enchant level.

Search matches anywhere in the name (“luna” also finds “Aluna”); exact matches and higher levels come first.

## Where the data comes from

Shugo.GG's own search and profile pages read two public NCSOFT endpoints; Shugo Tracker calls them directly:

- **Search:** `api-search.plaync.com/aion2global/search/v2/character` — one request per region, 30 results a page.
- **Details:** `aion2.plaync.com/api/character/info` — combat power, item level (gear score), stats, titles,
  Daevanion boards, legion.
- **Gear:** `aion2.plaync.com/api/character/equipment` — equipment, cosmetics, wings, pet and skills
  (only requested when you open a profile).

Details are only requested for cards on screen, newest scroll position first, by 4 parallel workers sharing a
rate limit (6 requests/s, halved automatically if the server says to slow down). Starting a new search
cancels the old one's pending requests.

Caching (all next to the app, in `character_cache.json` and `cache/`):

- card numbers are kept for 7 days and shown instantly; if older than 30 minutes they refresh quietly;
- profiles are kept for 7 days and shown instantly; if older than 10 minutes they refresh quietly;
- portraits (1 day) and game icons (30 days) are stored on disk;
- the same search within 15 minutes is answered from memory;
- resting the pointer on a card for a moment preloads its profile.

Delete the `cache` folder and `character_cache.json` at any time to start fresh.

## Updates

The **Check for updates** button sits at the top right of the window:

| button shows | meaning / what clicking does |
|---|---|
| Check for updates | asks GitHub for the latest release |
| ✓ Up to date | you have the newest version (goes back to *Check for updates* after a few seconds) |
| ⬇ Download v1.x.y | a newer version exists — click to download it (shows progress) |
| ⟳ Restart to update | downloaded and checksum-verified — click to switch to the new version |

The app also checks quietly at start-up and every 6 hours, so the button may already say
**Download** when you open it; nothing is downloaded until you click. If you quit with an update
downloaded, it's installed on exit. `config.json`, favorites and the cache are kept. Set
`"auto_update": false` to turn off the automatic checks (the button still works).

Builds made with `build_exe.bat` show **✓ Dev build** and are never replaced; running from source,
the button opens the release page instead.

## Development & publishing

The repo holds the source; the exe is only built when you publish.

- **Every push / PR** runs the tests on Windows (`.github/workflows/ci.yml`). No exe is built.
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
| `detail_workers` | `4` | parallel detail requests |
| `requests_per_second` | `6.0` | starting request rate (adapts down automatically) |
| `auto_update` | `true` | check for new releases at start-up and every 6 hours |
| `update_repo` | `"CynicaGaming/Shugo-Tracker"` | GitHub repo the updater follows |

The remaining keys belong to the experimental nearby overlay below.

## Experimental: nearby players overlay

Not part of the normal app yet — it will come back as an add-on. Run `ShugoTracker.exe --nearby`
**as administrator** with [Npcap](https://npcap.com) installed ("WinPcap API-compatible Mode") to get an
overlay that reads the game's network traffic and lists players in render range as Enemies / Allies.
It is read-only (no injection, no memory reading), but it is unproven against live play and does not yet
scale to crowded areas. Third-party tools may be against AION 2's terms of service; use at your own risk.

### Who shows up, and where

**Everyone in render range.** Players are added when the server sends their spawn record (they come into
view, or you load a map), removed when it sends the record that they left view, marked ✝ when they die,
and the whole list is reset when you load a new map (the server re-sends everyone around you). A player
whose leave record was missed is dropped after `forget_after_s` without activity.

**Enemy / ally.** AION 2 Global server ids encode faction: `race × 1000 + region × 100 + n`
(race 1 = Elyos, 2 = Asmodian; region 1 NA-East, 2 NA-West, 3 EU, 4 Latin America, 5 Asia). A player is:

- an **enemy** if their server or their Shugo.GG profile is the other faction, or they hit you / you hit
  them (⚡ for 15 s);
- an **ally** if their server or profile is your faction;
- **unidentified** until one of those is known.

Your own character and server come from the record sent when you log in or load a map. If you start the
tracker mid-session, load a map once or set `"my_server"` in `config.json` (e.g. `"nae-siel"`).

Spawn records usually carry name and class but not always the server. Then the tracker tries your server,
then the opposite-faction server paired with it (Siel ↔ Israphel), then `extra_enemy_servers` (enemy
servers first if they're fighting you). The Shugo profile's faction then settles enemy vs ally. A profile
found this way is marked **`?`**; hover to see which server was used, right-click → *Retry lookup*.

### Overlay controls

| | |
|---|---|
| drag the title bar | move (remembered) |
| click a section header | collapse / expand Enemies, Allies or Unidentified (remembered) |
| mouse wheel | scroll when the list is taller than `max_height` |
| left-click a player | open their Shugo.GG profile |
| right-click a player | open / retry lookup / copy name |
| hover a player | level, server, legion, hits on you in the footer |
| ⟲ / – / ✕ | clear list / minimise to the title bar / quit |

CP colours (enemies only) compare against **your** combat power, looked up once your character is seen.

### Nearby overlay settings (config.json)

| key | default | meaning |
|---|---|---|
| `my_server` | `""` | your server until the stream reveals it: `"nae-siel"`, `"eu-ludra"` or `1101` |
| `lookup_allies` | `true` | look up allies too. `false` = only enemies and unidentified players |
| `lookup_interval_s` | `2.0` | minimum seconds between Shugo.GG requests (floor 1.0) |
| `forget_after_s` | `900` | drop a player with no activity for this long (0 = never) |
| `collapsed_sections` | `[]` | sections collapsed at start: `"enemy"`, `"ally"`, `"unknown"` |
| `max_height` | `520` | list height in pixels before it scrolls |
| `extra_enemy_servers` | `[]` | more servers to try for players with no server, e.g. `["nae-zikel"]` |
| `kr_tw_region` | `"kr"` | Shugo path for Korean/Taiwanese server ids (`"kr"` or `"tw"`) |
| `interfaces` | `[]` | Npcap adapters to sniff; empty = all, including the loopback adapter (ExitLag etc.) |
| `opacity`, `position` | | overlay look and place |
| `auto_update` | `true` | download and install new releases (see *Automatic updates*) |
| `update_repo` | `"CynicaGaming/shugo-tracker"` | GitHub repo the updater follows |
| `opcodes` | | packet opcodes — see *After a game patch* |

### Being polite to Shugo.GG

Lookups go one at a time, at most one every `lookup_interval_s`, in this order: players fighting you,
enemies, unidentified, allies. Results are cached for 30 minutes (misses for 15) and HTTP 429/5xx backs off.
In a crowded town the queue grows (≈30 lookups a minute) — set `lookup_allies` to `false` if you mostly
care about enemies.

### After a game patch

Patches sometimes renumber opcodes (the June 2026 patch shifted the `xx 36` family by one). If names stop
appearing or players never leave the list, update the `opcodes` block in `config.json` from the open-source
meters' latest releases. To check a Wireshark capture (filter `tcp.port == 13328`, saved as `.pcapng`), from
source run:

```
python -m shugotracker.app --replay fight.pcapng --port 13328 --no-lookup --debug --console
```

The despawn (`42 36` / `35 36`) and map-load (`21 36`) records are the least battle-tested part: the meters
this is based on use them for NPCs and world objects; using them for players is new here.

### Limitations

- Player names only arrive with spawn records. Someone already in range when you start the tracker stays
  invisible until they re-enter view or you load a map.
- Shugo.GG only has what NCSOFT's public character API has; new characters or a site outage show `n/a` / `err`.
- Third-party tools may be against AION 2's terms of service. This one is read-only, like the DPS meters,
  but use it at your own risk.

## Credits & licence

The packet layouts were reverse-engineered and published by the open-source AION 2 meters —
[A2Tools-DPS-Meter](https://github.com/taengu/A2Tools-DPS-Meter),
[AIon2-Dps-Meter](https://github.com/Kuroukihime/AIon2-Dps-Meter),
[aion2-dps-meter](https://github.com/cyberbadger6969/aion2-dps-meter),
[Aion2DPSMeter](https://github.com/domel1998/Aion2DPSMeter) and
[aion2-combat-meter](https://github.com/mgauna-ar/aion2-combat-meter). The server table comes from A2Tools'
data. This is an independent Python implementation, released under **GPL-3.0** (see `LICENSE`).
Character data courtesy of [Shugo.GG](https://shugo.gg). Not affiliated with NCSOFT or Shugo.GG.
