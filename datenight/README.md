# Date Night Picker

A pink, heart-covered desktop app that picks a date night for you and your girlfriend from **over 1000 ideas** within an hour of **LE8 8AL (Fleckney, Leicestershire)**.

1. **How much would you like to spend?** Drag the heart along the slider, from free up to £200+ (the top means no limit). Prices are rough totals for two.
2. **How many minutes' drive from LE8 8AL?** Drag the heart from 0 (stay at home) to 60 minutes.
3. **Spin the love disc:** pick **Inside**, **Outside** or **Chill**. Click the heart in the middle for any vibe.
4. **When?** Any time, Daytime, Evening or Late night.

Then press **Pick our date night** (or Enter/Space). A heart spins round the disc with a little chime, the ideas shuffle, it lands on one with a burst of hearts, and it adds a random **cute twist** (like "wear matching colours"). **Directions** opens Google Maps from LE8 8AL, **Open?** checks today's opening hours, and **Pick another** rolls again without repeating recent picks.

**Not this one** says no to the idea and picks another straight away. It won't come up again for the rest of this session (until you close the app, or the tab on a phone). Next time you open the app, it's back in the mix, unless you've already done it. Ideas you've already done that you say no to stay out for good. **Memories** lists today's skips and the ones you've said no to for good, each with a **Bring back** button.

## Everything it can do

**Picking**
- **Seasons:** ideas only come up when they're on. Paddleboarding is summer only, and Christmas markets and the Christmas lights drive appear in November and December. Pumpkin picking, bonfire night, bluebell walks, strawberry picking and Valentine's ideas each have their own months. Short-season ideas are picked more often while they're on.
- **Weather:** today's Fleckney forecast (from [Open-Meteo](https://open-meteo.com), free, no account). If rain is likely, outdoor-only dates are picked less often.
- **Favourites** (**♥ Save**) are three times as likely to be picked. Dates you've already done are less likely.
- **Both of us:** each of you sets your own budget, drive and the vibes you're happy with, and it only picks dates you'd both say yes to.
- **Surprise mode:** the pick shows as "Top secret date" with clues only (drive time, budget, what to wear) until the planner presses **Reveal**.
- **+ Idea:** add your own date ideas with a form.

**Your relationship**
- **Settings:** your names, your anniversary and both birthdays. The top of the window counts down to the next one (for example "14 days until our 2nd anniversary"), and in the two weeks before, special dates (fancy dinners, spas, shows) come up more often and are marked "Perfect for our anniversary".
- **Date diary (in Memories):** a log of every date you've done, newest first, with hearts, notes and photos.
  - **+ Log a date** adds any date you've been on, including past ones and ones the app didn't pick. You set what you did, where, when, roughly what you spent, how it was (1–5 hearts), a note, the vibe and **as many photos as you like**.
  - **We did it!** on a picked date opens the same form, already filled in.
  - Each date has **Add photos** (to add more later), **Edit** and **Delete**, and every photo has a **×** to remove it. On the phone, tap a photo to see it full size.
- **Memories** also shows your stats, dates this month, your **streak** (weeks in a row with a date) and **badges** at 1, 5, 10, 25, 50, 75 and 100 dates. Each new badge gets a burst of hearts.
- **Year in review:** a pink "Our 2026 in dates" page with your stats, best date and photos. It opens in the browser, so you can print it or save it as a PDF. It would make a nice anniversary present.

**Practical**
- **Open?** looks up today's opening hours on OpenStreetMap (free). If the place isn't listed there, it opens a Google search for its opening times instead.
- **Copy for her** copies the plan with a Google Maps link for WhatsApp. **Calendar** saves an event with a reminder.
- **♪ On/Off** turns the little sounds on or off.
- **Back up / Restore** (in Memories) saves everything, photos included, into one file. Keep it on a USB stick or Google Drive. Restoring adds what's missing and never deletes anything, so you can restore the same file twice safely. If the same date was logged on both devices, you keep the photos from both.

Your memories, photos, favourites, own ideas and settings live in `~/.config/datenight`. Updating or uninstalling the app keeps them.

**Sync between devices:** see [On your phones](#on-your-phones) and [sync/README.md](sync/README.md).

## On your phones

The `web/` folder is a phone version with the same ideas and almost everything above: the four questions, seasons, weather, both of us, surprise mode, favourites, the date diary with photos, memories, streaks, badges, year in review, opening hours, sounds, sharing, calendar, and backup and restore. Sharing uses the phone's own Share button.

1. Put it online for free with GitHub Pages. On GitHub, open this repository, go to **Settings → Pages**, choose **Deploy from a branch**, pick the `claude/determined-bardeen-vvrlm3` branch and the **/ (root)** folder, then click **Save**.
2. After about a minute, open **https://kianpreston1-star.github.io/newproject263546/datenight/web/** in **Safari** on each iPhone.
3. A pink banner at the top explains how to install it: tap the **Share** button at the bottom of Safari, scroll down, tap **Add to Home Screen**, then **Add**.
4. From then on, open it from the **heart icon** on your home screen. It opens full screen like any other app, and the banner disappears.

As a home-screen app, it:

- **Works offline:** after the first open, it loads with no signal. Only the weather, Directions and Open? need the internet. Updates download by themselves in the background and show the next time you open it.
- **Keeps your data:** it asks iOS to keep its memories and photos rather than clearing them when space is short.
- **Shares backups through the iPhone share sheet:** **Back up** opens it, so you can send the file to each other on WhatsApp or save it to Files or iCloud. **Restore** reads it back.

The installed app keeps its data separately from Safari. If you've already logged dates in Safari, press **Back up** there first, then **Restore** inside the installed app.

A version in the App Store would need a Mac, Xcode and Apple's developer membership (£79 a year). The home-screen app gives you the same experience for free.

**Keeping the phones and the laptop in step:** turn on **sync** (Settings → **Sync between our devices**). Then dates, photos, edits, deletions, favourites, your own ideas, names and anniversary stay the same on both iPhones and the laptop, updating within a couple of minutes. It uses your own free Supabase project, which takes about 5 minutes to set up once: see **[sync/README.md](sync/README.md)**. Without sync, you can still move things between devices by pressing **Back up** on one and **Restore** on the other.

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
- Photo thumbnails: PNG photos always show. JPEGs (most phone photos) show if Pillow is installed (`sudo apt install python3-pil.imagetk`; the installer tells you if it's missing). Otherwise they still appear in the year in review.
- Sounds are generated by the app itself and played with `pw-play`, `paplay` or `aplay`, which Ubuntu already has.
- Everything is drawn on one canvas, and the floating hearts move about 26 small shapes 16 times a second, which barely registers on the CPU. The animation pauses while the window is minimised.
- All the ideas are stored in `ideas.json`, so it works offline. Only the weather check, the opening-hours check and the Directions button go online.
- The window is 940×680 and fits a 1366×768 screen with room for the panel.

## Where the 1000+ ideas come from

`ideas.json` has four parts:

- **ideas:** about 150 hand-written dates, plus 18 seasonal ones (Christmas, Halloween, Bonfire Night, Valentine's, spring and summer), such as Bradgate Park, Foxton Locks, Rutland Water, Warwick Castle, theatres, museums, steam railways and 40 cosy nights in.
- **towns:** about 50 real cities, towns and villages within an hour, each with its drive time from LE8 8AL.
- **templates:** date ideas that work in any town of a given size. For example, "Dinner date in {town}" becomes one idea for every town, so you get "Dinner date in Stamford", "Dinner date in Oakham" and so on. Village templates are things like a country pub lunch or a sunset walk. Other templates repeat over options, such as 16 cuisines to cook at home or 16 movie marathons.
- **twists:** 40 cute extras, and one is added to every date.

To add your own idea, put one line in the `ideas` list of `~/.local/share/datenight/ideas.json`:

```json
{"name": "Foxton Locks walk and pub", "where": "Foxton", "minutes": 15, "cost": 35,
 "vibes": ["outside", "chill"], "about": "What you'll do.", "maps": "Foxton Locks"}
```

`minutes` is the drive from LE8 8AL. Optionally, add `"times": ["day", "evening", "late"]` and `"months": [11, 12]`. `cost` is a rough total for two in pounds. `vibes` can include any of `inside`, `outside` and `chill`. `maps` is what Google Maps should search for; leave it empty for at-home ideas. If you add a town to `towns`, every matching template is applied to it as well. Running the installer again updates the list and saves your edited copy as `ideas.json.bak` first.

Drive times and prices are estimates. Town templates are general ("an escape room in Coventry"), so search Directions to find the actual place, and check opening times. Book ahead for shows, castles and seasonal places.

## Files

- `datenight.py`: the window. Run `python3 datenight.py --check` to test that it can start.
- `datecore.py`: the logic (picking, seasons, occasions, streaks, opening hours, sounds, backups, year in review).
- `web/`: the phone version (`index.html`, plus `sw.js`, which makes it work offline, and the app icons).
- `sync/`: `supabase.sql` (the one-time setup for syncing) and a step-by-step guide.
- `ideas.json`: the date ideas.
- `icon.svg`: the launcher icon.
- `install.sh`: the installer and uninstaller.
- `tests/`: checks for the picking, seasons, occasions, streaks, opening hours, backups, sharing, calendar and sync logic. `fake_supabase.py` is a stand-in sync server for the tests (`python3 -m pytest datenight/tests`).
