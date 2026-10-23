# Shugo Tracker

An always-on-top overlay for **AION 2** that lists **every player in render range**, split into collapsible
**Enemies** and **Allies** sections, with each player's **gear score** and **combat power** from
[Shugo.GG](https://shugo.gg). It reads the game's own network traffic through Npcap.

```
⚔ Shugo Tracker   3 enemies · 4 allies   ⟲ – ✕
▾ ENEMIES  3   top 151.3k CP
 ●  ⚡Morg          Templar     1,482  151.3k   ← red: stronger than you
 ●  Kesh            Sorcerer    2,670  96.2k    ← amber: within ±10%
 ●  ✝Vyrelle ?      Chanter     1,193  71.4k    ← green: weaker · ✝ dead · ? server guessed
▸ ALLIES  4                                    ← click a header to collapse / expand
▾ UNIDENTIFIED  1                              ← faction not known yet (only shown when non-empty)
 ●  Nameless        …           …      …
 Aerin 100.0k CP · capturing 1 game connection(s)
```

It is passive: it reads packets as they reach your PC and never sends, modifies or injects anything, and
never touches game memory — the same approach the community DPS meters use.

*Shugo Tracker is an independent fan tool; it uses Shugo.GG's public profile pages but is not made by or affiliated with Shugo.GG.*

## Install & run

1. Install **Npcap** from [npcap.com](https://npcap.com) with **"WinPcap API-compatible Mode"** ticked.
   (Npcap's licence doesn't allow bundling it, so it's a separate install.)
2. Download **`ShugoTracker.exe`** from the latest
   [release](https://github.com/CynicaGaming/shugo-tracker/releases/latest), put it in its own folder and run it.
   Windows asks for administrator rights — packet capture needs them. SmartScreen may warn the first time
   because the exe isn't code-signed: *More info → Run anyway*.
3. Play AION 2 in **borderless windowed** mode so the overlay can sit on top.

`config.json`, `shugo-tracker.log` and `shugo_cache.json` are kept next to the exe. Start it with `--demo`
(e.g. from a shortcut) to see the overlay with made-up players, no game needed.

## Automatic updates

The exe checks this repo's latest GitHub Release at start-up and every 6 hours. When a newer version exists
it downloads `ShugoTracker.exe` in the background and verifies it against the release's
`ShugoTracker.exe.sha256`. A green bar then appears under the title — click it to restart into the new
version. If you just quit instead, the update is installed on exit and the next launch is the new version.
Your `config.json` and cache are untouched. Turn it off with `"auto_update": false`.

Running from source, the bar only tells you a new version is out (`git pull`).

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
- `build_exe.bat` — build `dist\ShugoTracker.exe` on your PC (version shows as `0.0.0-dev`; dev builds never
  auto-update).
- `python -m unittest discover -s tests -t .` — tests.

## Who shows up, and where

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

## Overlay controls

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

## config.json

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

## Being polite to Shugo.GG

Lookups go one at a time, at most one every `lookup_interval_s`, in this order: players fighting you,
enemies, unidentified, allies. Results are cached for 30 minutes (misses for 15) and HTTP 429/5xx backs off.
In a crowded town the queue grows (≈30 lookups a minute) — set `lookup_allies` to `false` if you mostly
care about enemies.

## After a game patch

Patches sometimes renumber opcodes (the June 2026 patch shifted the `xx 36` family by one). If names stop
appearing or players never leave the list, update the `opcodes` block in `config.json` from the open-source
meters' latest releases. To check a Wireshark capture (filter `tcp.port == 13328`, saved as `.pcapng`), from
source run:

```
python -m shugotracker.app --replay fight.pcapng --port 13328 --no-lookup --debug --console
```

The despawn (`42 36` / `35 36`) and map-load (`21 36`) records are the least battle-tested part: the meters
this is based on use them for NPCs and world objects; using them for players is new here.

## Limitations

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
