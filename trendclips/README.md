# Trend Clips

Trend Clips makes short vertical videos (YouTube Shorts, TikTok, Instagram Reels) about whatever is trending, using free AI that runs on your own laptop. It sends each video to your phone, you tap ✅ or ❌, and then you post it. It costs **£0** to run.

```
 Google Trends ─┐
 Wikipedia ─────┤                    ┌─ facts from news articles + Wikipedia
 Reddit ────────┼─► pick safe, ──► research ─► script ─► AI voice ─► stock footage ─► captions, music, effects
 YouTube ───────┘   interesting                (Gemini)  (Kokoro)    (Pexels/Pixabay)          │
                    trends                                                                     ▼
       YouTube (optional auto-upload) ◄── ✅ Post / ❌ Skip on your phone (Telegram) ◄── finished 1080×1920 video
```

> **Read this first.** No tool can promise views or money. The platforms now demonetize mass-produced copycat content, so Trend Clips writes **original** scripts from the facts it researches and never reuses other people's clips. It also has **you approve every video**. That keeps your channel eligible for payouts. Most channels need 3 to 6 months of steady posting before they earn anything meaningful.

## What each video gets

- **A hook in the first second.** The opening line is written to stop the scroll, and a big headline pops up on screen for the first 2.5 seconds.
- **Captions people actually read.** Big, bold words appear 1 to 3 at a time and pop in. The word being spoken lights up, and key words get a second colour.
- **Fast cuts.** There's a new shot every 2 to 3 seconds. Each sentence gets its own stock clip, and a small image-matching AI (CLIP) checks the clip actually shows what's being said. Clips used in recent videos are avoided.
- **Movement and polish.** Every shot has a smooth slow zoom, with a punch-in and a whoosh at each scene change. There's a colour grade and a progress bar at the top.
- **Sound.** The voice is a natural-sounding AI voice (Kokoro). Your background music dips automatically under the voice, and the volume is levelled to −14 LUFS, the level YouTube and TikTok expect.
- **The subject on screen.** When Wikipedia has a photo of the subject under a free license, it opens the video, and the credit is added to the description for you.
- **A style per topic.** Sport, tech, money, showbiz, science, gaming and news each get their own fonts and colours, so a "whatever's trending" channel still looks deliberate.
- **Built to loop.** Scripts end on a line that flows back into the first one, so replays feel seamless, and replays count as views.
- **About 65 seconds long.** That's over a minute, which TikTok's Creator Rewards requires, and still a YouTube Short.
- **Safe topics only.** Deaths, tragedies, crime, disasters, politics and adult topics are filtered out twice: by keyword and by the AI picker.
- **Facts only from its research.** The script may only use what it found in news articles and Wikipedia. The sources are shown to you when you approve.

On a 2-core laptop (like a Dell Inspiron with an i5-7200U), a 65-second video takes roughly **5 to 10 minutes**. The daily run makes 2 while you get on with other things.

## Install (Ubuntu)

1. FFmpeg (the video engine) needs installing once. Open a terminal (**Ctrl+Alt+T**), then paste this and enter your password:

   ```bash
   sudo apt install -y ffmpeg
   ```

2. Install Trend Clips (no `sudo`):

   ```bash
   python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/trendclips/trendclips/install.sh', '$HOME/install-trendclips.sh')" && bash ~/install-trendclips.sh
   ```

The installer shows a ✔ for each step. It:

- sets up its own Python 3.12, leaving your system Python alone;
- downloads the free AI models (about 900 MB, once);
- asks for your free keys (next section). Press Enter to skip any; you can run `trendclips setup` later;
- turns on the daily run (17:30 by default) and the Telegram bot;
- adds a **Trend Clips** icon to your desktop and app menu. It makes a video right now and plays it when it's done.

Run the same command again to update. To uninstall, run `bash ~/.local/share/trendclips/install.sh --uninstall`. That keeps your keys in `~/.trendclips` and your videos in `~/Videos/TrendClips`.

Then make a test video, which needs no keys:

```bash
trendclips demo
```

## The free keys (about 10 minutes, once)

`trendclips setup` asks for each of these and tests it straight away. None needs a card.

| What | Why | How |
|---|---|---|
| **Gemini API key** (recommended) | Writes the scripts. Much better at hooks than a model running on the laptop. | Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey), sign in with Google, click **Create API key** and copy it. The free tier allows far more than a few videos a day. |
| **Pexels API key** (recommended) | Stock footage. Without it, videos use animated colour backgrounds. | Sign up at [pexels.com/api](https://www.pexels.com/api/) and copy **Your API Key**. |
| **Pixabay API key** (optional) | More footage to choose from. | Sign up at [pixabay.com](https://pixabay.com), then open [pixabay.com/api/docs](https://pixabay.com/api/docs/). Your key is shown under *Parameters*. |
| **Telegram bot** (recommended) | Videos arrive on your phone with ✅/❌ buttons. | In Telegram, message **@BotFather**, send `/newbot`, choose a name, and paste the token it gives you. Setup then asks you to press **Start** in your new bot, so it knows it's you. |
| **YouTube API key** (optional) | YouTube's trending list as an extra trend source, and view counts so the picker learns what works. | See [YouTube](#youtube-optional) below. |

**Offline backup writer (optional).** If Gemini is ever down or over its free limit, a small model on the laptop can take over. It's slower and writes less well, and it needs about 4 GB of free memory while it writes. To set it up:

```bash
sudo apt install -y curl zstd
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma3:4b
```

**Music.** Put 5 to 10 royalty-free tracks in `~/.trendclips/music/`. To match the mood, use subfolders named `energetic`, `dramatic`, `upbeat` and `chill`. Good free sources:

- [Pixabay Music](https://pixabay.com/music/): free for any platform. Very rarely a track gets a wrong copyright claim on YouTube; dispute it or swap the track.
- The **YouTube Audio Library** (YouTube Studio → Audio library): safe on YouTube. Check each track's license before using it elsewhere.

Without music, the voice and sound effects still play.

## Every day

1. At 17:30, or as soon as the laptop is on after that, Trend Clips checks what's trending. It picks the best 2 topics, researches them and makes the videos.
2. Each one arrives in Telegram with its title, where it's trending and where the facts came from. **Watch it and check the facts**, then tap **✅ Post it** or **❌ Skip**.
3. After ✅, the bot sends the caption and hashtags in tap-to-copy form. Save the video (tap it, then **⋮ → Save to Gallery**), post it on TikTok, YouTube Shorts and Instagram Reels, and paste the caption. On TikTok, adding a trending sound at very low volume helps reach.

You can also send the bot these commands:

| Command | What it does |
|---|---|
| `/make` | Makes a video about what's trending now. |
| `/make <topic>` | Makes a video about a topic you choose, e.g. `/make why the clocks go back`. |
| `/trends` | Shows what's trending, and what was skipped and why. |
| `/stats` | Shows your videos and their YouTube views. |

The laptop has to be **on and awake** for videos to be made and for taps to be handled. Keep it plugged in. Taps you send while it's off are handled when it wakes up.

## Commands

| Command | What it does |
|---|---|
| `trendclips setup` | Enter or change your keys. `--relink` reconnects Telegram. |
| `trendclips check` | Shows what's set up and working. `--deep` also tests the AI writer. |
| `trendclips demo` | Makes a test video. No keys needed. |
| `trendclips make` | Makes a video now. Options: `--count 2`, `--topic "…"`, `--no-send`, `--open`. |
| `trendclips trends` | Shows what's trending right now. |
| `trendclips stats` | Shows your videos and their views. |
| `trendclips schedule 18:00` | Changes the daily time. `schedule off` and `schedule on` stop and restart it. |
| `trendclips youtube-login` | Connects YouTube for automatic uploads. |
| `trendclips run` | The daily job, which the schedule runs for you. |

Settings live in `~/.trendclips/config.toml`. [`config.example.toml`](trendclips/config.example.toml) explains every one: videos per day, video length, voice (`af_heart` by default; `"auto"` picks one per topic), music volume, your @handle, trend regions, words to avoid, and more.

## YouTube (optional)

**API key, for trends and view counts.**

1. Open [console.cloud.google.com](https://console.cloud.google.com/), and create a project (top left, then **New project**, called *Trend Clips*).
2. Go to **APIs & Services → Library**, search for **YouTube Data API v3**, and click **Enable**.
3. Go to **APIs & Services → Credentials → Create credentials → API key**, then copy it into `trendclips setup`.
4. Setup also asks for your channel ID. It starts with `UC` and is shown at [youtube.com/account_advanced](https://www.youtube.com/account_advanced).

**Automatic uploads.** Google only lets *audited* apps publish public videos through its API. Until your project passes Google's free audit, anything it uploads is locked to private. So for most people, posting from the phone (step 3 above) is simpler. If you want to set it up anyway:

1. In the same project, open **Google Auth Platform** (OAuth consent screen). Choose **External**, enter an app name and your email, and add yourself under **Audience → Test users**.
2. Click **Publish app** under Audience, so your sign-in doesn't expire every 7 days. When you sign in, Google warns the app is unverified: click **Advanced → Go to Trend Clips**. It's your own app.
3. Go to **Credentials → Create credentials → OAuth client ID → Desktop app**, download the JSON, and save it as `~/.trendclips/youtube-client-secret.json`.
4. Run `trendclips youtube-login`. From then on, ✅ uploads to YouTube automatically.
5. To publish publicly, apply through Google's *YouTube API Services Audit and Quota Extension* form.

## Staying monetizable

- **YouTube Partner Program:** 1,000 subscribers plus 10 million Shorts views in 90 days, or 4,000 watch hours. Repetitive, mass-produced videos are not eligible. That's why every script is original and you approve each one.
- **TikTok Creator Rewards:** 10,000 followers, 100,000 views in the last 30 days, and original videos over 1 minute. It's available in the UK.
- **Disclose AI when asked.** The voice is AI. On TikTok, turn on the **AI-generated content** label. On YouTube, tick *altered or synthetic content* when a video could be mistaken for real footage of real events. If in doubt, disclose.
- **Rights.** Pexels and Pixabay footage is free for commercial use with no credit required. Wikipedia photos are only used under public-domain, CC0 or CC BY licenses, with the credit added to the description automatically. CC BY-SA photos are off by default (`allow_share_alike_images`), because their share-alike terms are murkier for videos. Only use music you have the right to use.
- **Post 1 to 3 videos a day**, not dozens. Mass posting gets accounts flagged.
- **Reply to comments.** It helps reach more than anything else here.
- **The money paths, best first:** sponsorships and affiliate links once you have an audience, then platform payouts. Shorts pay very little per view.

## If something goes wrong

- **`trendclips check`** shows what isn't set up, with what to do next to each ✘.
- **The log** is in `~/.trendclips/trendclips.log`.
- **"No AI writer".** Add a Gemini key with `trendclips setup`, or install Ollama (above).
- **Videos have no stock footage.** Add a Pexels key. Check that `trendclips check` shows *Stock footage: Pexels*.
- **Telegram buttons don't respond.** The bot only runs while the laptop is on. Restart it with `systemctl --user restart trendclips-bot`, or reconnect with `trendclips setup --relink`.
- **No systemd** (rare on Ubuntu). Run `crontab -e` and add `30 17 * * * ~/.local/bin/trendclips run`.

## How it works (files)

| File | Job |
|---|---|
| `trendclips/trends.py` | Reads Google Trends, Wikipedia's suddenly-popular pages, Reddit and YouTube. Merges duplicates, ranks topics, and drops sensitive ones. |
| `trendclips/research.py` | Reads the news articles behind a trend, plus Wikipedia, and finds a freely licensed photo. |
| `trendclips/writer.py` | The AI editor (picks trends) and scriptwriter (hook, scenes, footage searches, title, hashtags). Also checks script length. |
| `trendclips/llm.py` | Gemini's free tier, any OpenAI-compatible API, or Ollama, each falling back to the next. |
| `trendclips/voice.py` | The Kokoro voice, plus Whisper word timings matched back to the script's own words. |
| `trendclips/footage.py` | Pexels and Pixabay search. Picks a sharp file without wasting effort on 4K, and ranks clips with CLIP. |
| `trendclips/captions.py`, `themes.py`, `sfx.py` | Animated ASS captions, the per-topic looks, and sound effects synthesized from scratch. |
| `trendclips/render.py` | FFmpeg. Each shot is rendered separately with a smooth zoom (a broken clip only loses one shot). The final pass adds captions, the progress bar, music ducking and loudness levelling. The file is sized to fit Telegram's 50 MB limit. |
| `trendclips/pipeline.py` | Runs the whole thing: one job at a time, cleaning up week-old downloads. |
| `trendclips/telegram.py`, `youtube.py`, `cli.py` | Your phone controls, YouTube uploads and stats, and the commands. |

Run the tests with:

```bash
cd trendclips && pip install -e ".[test]" && pytest
```
