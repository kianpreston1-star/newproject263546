# Date Night Picker

A small desktop app that picks a date night for you and your girlfriend, within an hour of **LE8 8AL (Fleckney, Leicestershire)**.

1. **How much would you like to spend?** A slider from free up to £200+ (the top means no limit). Prices are rough totals for two.
2. **How many minutes' drive from LE8 8AL?** A slider from 0 (stay at home) to 60 minutes.
3. **Pick a vibe** on the disc: **Inside**, **Outside** or **Chill**. Click the middle for any vibe.

Then press **Pick our date night** (or Enter/Space). A marker spins round the disc, the ideas shuffle, and it lands on one. **Directions** opens Google Maps with the route from LE8 8AL, and **Pick another** rolls again without repeating your recent picks. The app remembers your last answers.

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
- All 56 ideas are stored in `ideas.json`, so it works offline. Only the Directions button goes online.
- The window is 900×580 and fits a 1366×768 screen with room for the panel.

## Add your own ideas

Edit `~/.local/share/datenight/ideas.json`. Each idea looks like this:

```json
{"name": "Foxton Locks walk and pub", "where": "Foxton", "minutes": 15, "cost": 35,
 "vibes": ["outside", "chill"], "about": "What you'll do.", "maps": "Foxton Locks"}
```

`minutes` is the drive from LE8 8AL. `cost` is a rough total for two in pounds. `vibes` can include any of `inside`, `outside` and `chill`. `maps` is what Google Maps should search for; leave it empty for at-home ideas. Running the installer again updates the list and saves your edited copy as `ideas.json.bak` first.

Drive times and prices are estimates. Check opening times and book ahead for shows, castles and seasonal places.

## Files

- `datenight.py`: the whole app. Run `python3 datenight.py --check` to test that it can start.
- `ideas.json`: the date ideas.
- `icon.svg`: the launcher icon.
- `install.sh`: the installer and uninstaller.
- `tests/`: checks for the matching and picking logic (`python3 -m pytest datenight/tests`).
