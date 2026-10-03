# Operating playbook

How to actually get views and (eventually) money out of the machine. The workflows handle
production; this is the strategy layer that decides whether it works.

## The honest model

The machine removes the *work* of making and posting content. It does **not** remove the need for a
good **niche**, a good **hook**, and **iteration**. Expect the first few weeks to be data-
gathering: post consistently, watch which videos pop, double down on those, cut what flops. The
creators who win with automation treat it as "10× the at-bats," not "set it and forget the
strategy."

## Step 1 — Pick a niche (do this well; it's 80% of the outcome)

Good automated niches share three traits: **endless source material**, **clear audience**, and
**low face/personality requirement**. Examples:

- **Clip engine niches** (needs CC long-form to exist): educational talks, public-domain
  documentaries, tech/AI lectures, finance explainers, history, science. Search the niche with the
  CC filter first — if there's little CC footage, pick another.
- **AI-generated niches:** "did you know" facts, motivation, top-5 lists, explainer/"how X works",
  story-time, niche news recaps. Pick one lane and stay in it per channel.

Set 3–8 niche keywords in the config sheet. One niche per channel/account.

## Step 2 — Dial in the hook

The first 1–2 seconds decide everything on short-form. The prompt packs in `prompts/` generate
multiple hook styles; the variety injector rotates them. After ~20–30 posts, look at retention and
hard-code your 2–3 best-performing hook styles into the active prompt pack.

## Step 3 — Cadence

- Start **1–2 posts/day per platform**. Enough to learn, not enough to look spammy.
- Keep the stagger offsets (config) so posts land at platform-appropriate times, not all at once.
- Scale up only after a format proves out. More bad videos ≠ more views.

## Step 4 — Platforms

Post the same short everywhere the format fits, but know the differences:
- **YouTube Shorts** — best long-term discovery + the clearest monetization path.
- **TikTok** — fastest viral potential; remember its program bars pure-AI (favor clip engine here).
- **Instagram Reels** — strong reach; Reels reward trends/audio.
- **Facebook / Pinterest / LinkedIn / X / Threads / Bluesky** — low effort to add via the posting
  API; treat as free extra reach, not primary.

## Step 5 — Read the data, iterate

Weekly: open the `log` tab + each platform's analytics. For the top ~10% of videos, note niche sub-
topic, hook, length, and visual style. Feed those back into the config keywords and the active
prompt pack. Kill sub-topics that consistently flop. This feedback loop is what compounds.

## Monetization path (when you're ready)

You chose **views first** — correct for the start, because every money path needs an audience or
traffic first. In rough order of how soon they can pay:

1. **Affiliate / your own product (day one, no minimums).** Put a relevant affiliate link or your
   own digital product (template, ebook, tool) in the bio/description. Views → clicks → revenue
   with zero follower gate. This is the most realistic early income and works even at small scale.
2. **Platform ad revenue (needs thresholds).** YouTube Partner Program: 1k subs + 4k watch-hrs or
   10M Shorts views/90d. TikTok rewards: 10k followers + 100k views/7d (and not for pure-AI). Turn
   on once you clear the bar.
3. **Sponsorships / brand deals (needs a following).** Once a channel has a defined niche audience,
   brands in that niche will pay for integrations.
4. **Grow & sell.** A faceless channel with a real following and revenue is a sellable asset.

To switch on affiliate links now: add your link + a per-niche call-to-action line to the caption
section of the active prompt pack; the posting step will include it automatically.

## Scaling

Once one channel + niche works:
- **Clone the config** for a second niche/account — same workflows, new config tab + credentials.
- Move from Shoestring → Starter tier (`COSTS.md`) for daily volume and better clipping.
- Only add the premium AI-video branch when a niche clearly benefits from motion video; it's the
  biggest cost lever.

## What to check if views are flat

1. Is the hook landing in the first 2s? (retention graph) → change hook pack.
2. Is the niche too broad or too crowded? → narrow it.
3. Are videos too similar? → the variety injector helps, but you may be in a templated rut; refresh
   prompt packs.
4. Posting at bad times? → adjust stagger offsets.
5. Wrong platform for the format? → focus where retention is best.

The plumbing running isn't the goal — a format that earns watch-time is. Give it real iteration.
