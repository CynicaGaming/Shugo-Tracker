# What's new

Each release's notes come from its section here (shown in Settings → Updates). Keep each line short.

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
