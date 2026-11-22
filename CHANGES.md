# What's new

Each release's notes come from its section here (shown in Settings → Updates). Keep each line short.

## 2.6.5
- New: a Server filter (Filters → Server): pick one server, e.g. Kaisinel · NA East, and Search asks NCSOFT for that server only (so totals are right); Favorites, Nearby and Recent show just that server too

## 2.6.4
- Fixed: "A JavaScript error occurred in the main process" (the 'screen' module…) that could pop up while the app was starting

## 2.6.3
- Changed: the column menu (right-click the headers) only lists the columns that tab has: Last Seen and Area only on Recent

## 2.6.2
- New: an Area column on Recent: the map each player was last seen in. The game only sends a number (Map 1010), so right-click a player → Name This Area to call it what it is; your names stick
- Area is blank where the game loads you in without a map number (Shugo, some instances and returns)

## 2.6.1
- Fixed: with Click Through on, a pop-out's title bar couldn't be clicked either (so there was no way back). The app now watches the cursor itself: over the title bar the pop-out takes the mouse, anywhere else the game does; Alt still makes the whole pop-out clickable
- New: right-click a popped-out tab in the main window to show its pop-out, turn off its Click Through, or close it

## 2.6.0
- New: Click Through for each pop-out (its gear): your clicks go to the game, except on its title bar; hold Alt to use the whole pop-out
- New: Lock Position for each pop-out (its gear): it can't be moved or resized until you unlock it
- New: pop out any tab: right-click Search, Favorites or Recent → Pop Out (clicking a player opens them in the main window)
- New: Clear PVP Log (right-click the PVP tab) to start fresh; the cleared fights are kept aside in the data folder, just in case
- Nearby is out of beta
- Behind the scenes: real arena, open-world, duel, Abyss and PvE fights now run as tests before every release

## 2.5.9
- Changed: Alert Every is now called Alert Cooldown

## 2.5.8
- Changed: Alert Sound is a dropdown: Chime, Ping, Bell, Beeps, Alarm, War Drum, or Custom… to pick your own file (it then stays in the list); each plays when you pick it

## 2.5.7
- New: Enemy Alert (Settings → Nearby): a sound when an enemy shows up on Nearby, at most once per 10s … 10m, at the volume you set
- New: use your own sound for it (Choose… picks an mp3, wav, ogg or m4a; it's kept in the data folder beside the app), or the built-in chime; Test plays it

## 2.5.6
- Fixed: a sliver of the list showed above the Nearby pop-out's headers when scrolled

## 2.5.5
- Fixed: after entering a new area (the Abyss especially), Nearby and the PVP Log could miss that you're you, so your kills and deaths there went unlogged

## 2.5.5
- New: duels go in the PVP Log (marked Duel): the game says who won, so a lost duel is a death and a won one a kill
- Fixed: a killer named by the game is logged with their exact server
- The core log now notes each id the game gives you and every kill record about you or a player near you, so a missed fight can be traced

## 2.5.4
- Fixed: the PVP Log missed kills and deaths outside arenas. In the open world the game's kill record also names the killer (and their server), which the log now reads, so even a killer you never saw is logged

## 2.5.3
- New: each pop-out has a gear with its own Opacity and Always on Top
- New: the Nearby pop-out has column headers: click one to sort, right-click to add or remove Legion, Class, Level, Server, Gear Score and Combat Power
- New: K/D in the PVP pop-out's title, beside today's kills, deaths and assists
- Changed: no Elyos / Asmodian headings in the Nearby pop-out (the coloured stripe shows the side; enemies stay on top)

## 2.5.2
- New: Pop Out PVP (right-click the PVP tab): today's kills, deaths and assists, then your latest fights as a kill feed; click one to open that opponent in the main window
- Removed: the gear button on pop-outs

## 2.5.1
- Changed: the HUD is now its own window: right-click the Nearby tab → Pop Out Nearby. It stays on top over the game while the main window does whatever you like; it reopens next time if you left it open
- Changed: clicking a player in the pop-out (or its gear) opens their profile (or Settings) in the main window
- Changed: gear score is shortened in the pop-out too (1.9k)
- Removed: the Style setting (the pop-out replaces it; if you used the HUD style, Nearby pops out on its own)

## 2.5.0
- New: HUD style (Settings → Window → Style): a slim, always-on-top Nearby list to keep over the game, with each player's class, combat power and gear score, enemies first
- New: in the HUD, click a player (or the gear) and the window opens full size for their profile (or Settings); Back returns to the HUD
- Each style remembers its own window size and place

## 2.4.5
- New: the logo (in the window and on the taskbar) turns grey while AION 2 isn't running, and back to gold when it starts

## 2.4.4
- New: resize columns on Search, Favorites, Nearby and Recent: drag the line between two headers (double-click it to undo; Reset Columns in the header's right-click menu resets them all)

## 2.4.3
- Changed: the PVP Log's dates are one pill like the other tabs' Filters: Today, Last 7 Days, Last 30 Days, All Time, or pick your own From and To dates; Clear resets it

## 2.4.2
- Fixed: the PVP Log missed kills and deaths: it now reads the game's own kill record, which names the killing blow

## 2.4.1
- Changed: the tab is called PVP
- Changed: each fight reads like a kill feed: the winner, crossed swords, then the one who fell, in green when you won and red when you didn't
- Changed: an opponent's page shows who they are at a glance: legion, class, server, faction, combat power, gear score and level

## 2.4.0
- New: PVP Log — who you killed, who killed you, and assists, recorded while Nearby is on
- New: click someone in the PVP Log to see every fight with them, filtered to the last 24h, 7d, 30d or all time

## 2.3.30
- Changed: no mark at 50 on the deity stat bars (they still run 0 to 100)

## 2.3.29
- Fixed: 2.3.28 wouldn't open (a typo in the Stats page)
- Changed: deity stat bars run 0 to 100, with a mark at 50

## 2.3.28
- Changed: deity stat bars run 0 to 100, with a mark at 50

## 2.3.27
- Changed: main stats in the game's order: Might, Dexterity, Precision, Willpower, Intelligence, Constitution

## 2.3.26
- Fixed: clearing the search box goes back to the start instead of leaving the old results
- Changed: "Asmodian" everywhere (filters, Nearby headers), matching Elyos and the game

## 2.3.25
- Fixed: empty gear slots showed as tall boxes instead of square tiles

## 2.3.24
- Changed: Switch Profile is now Switch Character, and Set Profile is Set as My Character

## 2.3.23
- Changed: Switch Profile always opens to the right (the menu makes room for it)

## 2.3.22
- Changed: title effects read like stat rows (name left, value right) instead of a bulleted list

## 2.3.21
- Changed: with both clocks shown, LT always shows its date too

## 2.3.20
- Changed: titles show the equipped effect on top and the owned effect under a line, dimmer, like the game (no labels)

## 2.3.19
- Fixed: hovering an item sometimes showed no tooltip at all
- Changed: comparing with ALT keeps Equipped on your item's card, with both items level side by side
- Changed: titles show their Equipped Effect and Owned Effect separately
- Changed: click the footer clock to cycle ST, LT, or both
- Removed: the Clear button for Recent Players in Settings (right-click Recent to clear it)

## 2.3.18
- Changed: item tooltips open beside the window instead of over your gear
- Changed: comparing with ALT shows both items side by side, tops level, with Equipped above yours

## 2.3.17
- Changed: Clear Nearby works like it used to: anyone still around comes back on their next move, and those who left stay on Recent

## 2.3.16
- Fixed: Nearby froze (looked slow or missing people) whenever someone nearby had a Chinese, Korean or other non-Latin name
- Fixed: searching for a non-Latin name works the same way

## 2.3.15
- Fixed: closing the app could show "A JavaScript error occurred in the main process" (write EPIPE)
- Fixed: the window's size and position are saved reliably when the app closes

## 2.3.14
- Nearby's "showing arrivals" footer note is gone

## 2.3.13
- Nearby starts fresh again after a restart (2.3.12's saved list is undone)

## 2.3.12
- Fixed: restarting the app (an update, say) no longer empties Nearby; its list comes back if you're still in the same area, and Recent is kept too

## 2.3.11
- Nearby says when its list is partial: players already around when it started only appear once you change area

## 2.3.10
- Fixed: with a region, class or level filter on, Nearby no longer hides players whose details haven't loaded yet

## 2.3.9
- Settings: Check Automatically without the note under it

## 2.3.8
- An update now shows as a small green blip on the logo; click the logo for Settings → Updates
- Menus, buttons, headings and settings use Title Case throughout (My Profile, Add to Favorites, Always on Top)
- Settings ends with the NCSOFT notice

## 2.3.7
- Fixed: Nearby in Shugo Festival lists the match's players (from its scoreboard), even when Nearby starts mid-match
- Fixed: entering an instance moves the town crowd to Recent, even when the game sends no map change
- Logs are one file a day (shugo-core_2026-11-15.log, nearby_2026-11-15.bin): every start that day adds to it;
  text logs are kept 14 days, Nearby's traffic 7 days; the logs also note each player seen and every area change

## 2.3.6
- Daevanion: hover a skill node, or a skill under Skill Effect, for that skill's tooltip at the character's level
- Stats: bonuses read "Attack +5.6%" instead of "Attack increase +5.6%"
- Skill tooltips no longer carry a credit line

## 2.3.5
- Fixed: restarting for an update starts the new version again (the administrator restart from 2.3.1 is undone)
- An update now shows as a small arrow beside the logo; click it for Settings → Updates
- Check automatically: Never, 30m, 1h, 6h, 12h or 24h; it also checks when the app starts and when Settings opens

## 2.3.4
- Daevanion: every board fits the window without scrolling; Board Effect below it, split into Skill Effect and Stat Effect like the game
- Daevanion node tooltips show just the node and what it gives

## 2.3.3
- New Stats tab: main stats as tiles and the ten deity stats as meters, each with the game's description on hover

## 2.3.2
- An update now shows as a dot on your profile picture (green: ready, gold: installing); its button is at the top of that menu

## 2.3.1
- Fixed: with Nearby on, restarting for an update starts the new version as administrator, so Nearby keeps working

## 2.3.0
- Smoother lists: scrolling and live updates reuse rows instead of rebuilding them, so portraits no longer reload
- The title bar only redraws when something on it changes
- Lighter background work: requests share a small pool of workers, and settings are saved safely
- Cleanup: about 1,000 lines left over from the old window removed, and settings code in one place

## 2.2.8
- The region switch spells out Europe and Latin America; pick none to search every region

## 2.2.7
- New look for the filters: one region switch, Elyos and Asmodians toggles, and a Filters button (with a count) for class and level
- Region names tidied up: NA East, NA West, Europe, Latin America, Asia

## 2.2.6
- Updates is now first in Settings, with simpler buttons: Download, Installing…, Restart

## 2.2.5
- Settings is shorter: no Data section or Nearby status

## 2.2.4
- Logs are named by when they started (for example shugo-core_2026-11-14_22-51-03.log); the newest few are kept, none older than 14 days
- Every log line starts with the full date and time, to the millisecond

## 2.2.3
- Nearby groups players as Elyos and Asmodians (the enemy faction first), in the filters' colours
- Nearby keeps a running log of what it reads, so there's nothing to record when something goes wrong
- Fixed: turning on Nearby from its tab shows the filters straight away

## 2.2.2
- Fixed: Nearby works again after a normal start (it restarts as administrator by itself, as before)
- New: Nearby's status in Settings
- Titles no longer show how many players own them

## 2.2.1
- Fixed: with the pin on, the window no longer slips under other apps or the game

## 2.2.0
- New: Settings → Updates shows your version, what's new, and when it last checked
- New: find your character on first start (region, server, name), or Add character from your name
- New: portraits in every list; Titles in the game's order; the stat wheel laid out like the game
- Fixed: Clear Nearby stays cleared; the window can always be brought back by starting the exe again
- Faster: starts in about a second after the first launch of each version
