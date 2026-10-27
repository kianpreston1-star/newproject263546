# Date Night Picker

A pink, heart-covered desktop app that picks a date night for you and your girlfriend from **over 1000 ideas** within an hour of **LE8 8AL (Fleckney, Leicestershire)**.

1. **How much would you like to spend?** Drag the heart along the slider, from free up to £200+ (the top means no limit). Prices are rough totals for two.
2. **How many minutes' drive from LE8 8AL?** Drag the heart from 0 (stay at home) to 60 minutes.
3. **Spin the love disc:** pick **Inside**, **Outside** or **Chill**. Click the heart in the middle for any vibe.

Then press **Pick our date night** (or Enter/Space). A heart spins round the disc, the ideas shuffle, it lands on one with a burst of hearts, and it adds a random **cute twist** (like "wear matching colours" or "plan your next date before you get home"). **Directions** opens Google Maps with the route from LE8 8AL, and **Pick another** rolls again without repeating your recent picks. The app remembers your last answers.

## Extras

- **Weather check:** when the app opens, it fetches today's forecast for Fleckney and shows it in the top right. If rain is likely, outdoor-only dates are picked less often, and any that do come up get a "take a brolly" note. The forecast comes from [Open-Meteo](https://open-meteo.com), which is free and needs no account. If you're offline, the app works as normal without it.
- **♥ Save** adds a date to your favourites, which are three times as likely to be picked.
- **We did it!** logs the date with a 1–5 heart rating and a note. Dates you've done come up less often, so you keep trying new things. If one does come up again, the card shows how you rated it last time.
- **Our memories** (top right) lists every date you've logged, your stats (dates, money spent, average rating, favourite vibe), your favourites and your own ideas. It also has a button to pick one of your favourites.
- **+ Add idea** lets you add your own date ideas with a form. They're saved separately from the built-in list, so updates never wipe them.
- **Surprise mode:** turn it on, and the next pick is shown as "Top secret date" with clues only: drive time, budget, vibe and what to wear. The planner presses **Reveal** to see it. **Copy for her** and **Calendar** keep the secret too.
- **Copy for her** copies a ready-made message with the plan, the cute twist and a Google Maps link. Paste it into WhatsApp with Ctrl+V while the app is open.
- **Calendar** saves a calendar file (`.ics`) to your Desktop for tonight, tomorrow or a Saturday. It includes a reminder two hours before. Open it, or import it into Google Calendar or your phone's calendar.

Your memories, favourites and own ideas are stored in `~/.config/datenight/memories.json`. Updating or uninstalling the app keeps them.

## Install on Ubuntu (one command)

Open a terminal (**Ctrl+Alt+T**), paste this line and press Enter:

```bash
python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/determined-bardeen-vvrlm3/datenight/install.sh', '$HOME/install-datenight.sh')" && bash ~/install-datenight.sh
```

Run it as yourself, not with `sudo`. If Ubuntu is missing Tkinter (the window toolkit), the installer asks for your password once to run `sudo apt install python3-tk`.

Afterwards, open it from:

- **Desktop:** double-click the pink heart icon. On XFCE, the installer marks it as trusted, so it opens straight away. If you're asked anyway, choose **Launch Anyway** or **Mark Executable**.
- **App menu:** look under **Accessories**, or search for **Date Night**.

**Update:** run the same command again. **Uninstall:** `bash ~/.local/share/datenight/install.sh --uninstall`

## Made for your laptop

It was built for a Dell Inspiron 15-3567 (i5-7200U, 8 GB RAM) running Ubuntu 26.04 with XFCE on X11:

- It's plain Python and Tkinter, so there's no browser, no Electron and no pip packages. It uses about 30 MB of RAM and no CPU while idle.
- Everything is drawn on one canvas, and the floating hearts move about 26 small shapes 16 times a second, which barely registers on the CPU. The animation pauses while the window is minimised.
- All the ideas are stored in `ideas.json`, so it works offline. Only the start-up weather check and the Directions button go online.
- The window is 940×620 and fits a 1366×768 screen with room for the panel.

## Where the 1000+ ideas come from

`ideas.json` has four parts:

- **ideas:** about 140 hand-written dates, such as Bradgate Park, Foxton Locks, Rutland Water, Warwick Castle, theatres, museums, steam railways and 40 cosy nights in.
- **towns:** about 50 real cities, towns and villages within an hour, each with its drive time from LE8 8AL.
- **templates:** date ideas that work in any town of a given size. For example, "Dinner date in {town}" becomes one idea for every town, so you get "Dinner date in Stamford", "Dinner date in Oakham" and so on. Village templates are things like a country pub lunch or a sunset walk. Other templates repeat over options, such as 16 cuisines to cook at home or 16 movie marathons.
- **twists:** 40 cute extras, and one is added to every date.

To add your own idea, put one line in the `ideas` list of `~/.local/share/datenight/ideas.json`:

```json
{"name": "Foxton Locks walk and pub", "where": "Foxton", "minutes": 15, "cost": 35,
 "vibes": ["outside", "chill"], "about": "What you'll do.", "maps": "Foxton Locks"}
```

`minutes` is the drive from LE8 8AL. `cost` is a rough total for two in pounds. `vibes` can include any of `inside`, `outside` and `chill`. `maps` is what Google Maps should search for; leave it empty for at-home ideas. If you add a town to `towns`, every matching template is applied to it as well. Running the installer again updates the list and saves your edited copy as `ideas.json.bak` first.

Drive times and prices are estimates. Town templates are general ("an escape room in Coventry"), so search Directions to find the actual place, and check opening times. Book ahead for shows, castles and seasonal places.

## Files

- `datenight.py`: the whole app. Run `python3 datenight.py --check` to test that it can start.
- `ideas.json`: the date ideas.
- `icon.svg`: the launcher icon.
- `install.sh`: the installer and uninstaller.
- `tests/`: checks for the picking, weather, memories, sharing and calendar logic (`python3 -m pytest datenight/tests`).
