# Compliance & guardrails

Read this before you go live. Autonomous content systems get accounts killed when they ignore
platform rules. The machine is built to stay on the safe side by default — here's how, and what
stays your responsibility.

## 1. Clip sourcing is Creative-Commons / licensed only

The clip engine **only** pulls sources you're allowed to reuse. It queries the YouTube Data API
with `videoLicense=creativeCommon`, so results are limited to videos the uploader released under
the **Creative Commons Attribution (CC BY)** license.

- **Do not** reconfigure it to clip arbitrary channels you don't own or have no license for.
  Re-uploading others' content triggers Content ID claims, copyright strikes, YouTube's "reused
  content" demonetization, and can get accounts banned. That defeats the entire "runs flawlessly"
  goal.
- If you have your **own** long-form channel or **explicit permission/licensing** from a creator,
  you can add those as fixed sources (RSS by channel ID) — that's also safe.

### Attribution is automatic
CC BY requires crediting the original author. The workflow + `scripts/cc_attribution.py` build an
attribution line (title, author, source URL, license) and append it to each post's description/
caption. **Don't remove this step** — without it you're out of license compliance even on CC video.

## 2. Avoid "inauthentic / mass-produced content" throttling

YouTube's inauthentic-content policy (renamed from "repetitious content" in 2025) demonetizes
*mass-produced, templated, low-effort* video — whether AI-made or not. The three buckets it hits
hardest: verbatim readings of material you didn't create, reused templates with identical
structure, and bare slideshows/scrolling text with no commentary.

How the machine stays clear:
- **Transform step (Engine 1):** every clip gets an added hook/title overlay and your caption
  style, so it's a reframed/commented short, not a bare reupload.
- **Variety injector (Engine 2):** the script node randomizes hook style, structure, pacing, and
  B-roll direction per run, so outputs don't look templated.
- **One brand voice per channel** and a capped cadence (config) keep each account looking like a
  real creator, not a spam farm.

Your part: pick a niche where you add a point of view, and swap in fresh prompt packs over time.
Pure firehose output of near-identical videos will still get throttled no matter the tooling.

## 3. AI disclosure

YouTube (and others) require disclosing realistic synthetic media. The posting step has an
**AI-disclosure toggle** (set per engine in config): when Engine 2 produces AI voice/video, it
sets the platform's synthetic-media flag and/or adds a disclosure line to the description.
Consistently skipping disclosure risks removal or Partner Program suspension — leave it ON for the
AI engine.

## 4. Posting hygiene (anti-spam)

- **Staggered scheduling:** posts are spread with per-platform offsets instead of fired all at
  once — bulk-at-once posting looks like spam and gets rate-limited or shadow-limited.
- **Cadence cap** in config: keep per-platform posts within normal creator ranges (a handful a day,
  not dozens).
- **Dedupe:** the `log` tab prevents re-posting the same clip/topic.
- **Respect each platform's API terms** for your posting provider (upload-post / Blotato handle the
  official API connections; don't bolt on unofficial auto-posters that violate ToS).

## 5. Monetization reality (you chose "views first")

You don't need to monetize to run this, but when you want to turn earnings on, know the bars:
- **YouTube Partner Program:** 1,000 subscribers **+** 4,000 public watch-hours (long-form) in 12
  months, **or** 1,000 subs + 10M Shorts views in 90 days. AI-assisted content is eligible *if*
  it's disclosed and adds genuine value; mass-produced slop is not.
- **TikTok Creator Rewards:** 18+, 10k followers, 100k views in 7 days — **and it effectively bars
  primarily-AI content** from payout. For TikTok, lean on the clip engine (real source footage) or
  monetize off-platform.
- **Earns from day one, no follower minimum:** affiliate links and your own digital products. This
  is the realistic early revenue path — see `PLAYBOOK.md`.

## 6. Legal / housekeeping

- Music: use only licensed/royalty-free or platform-provided audio libraries. Don't let a render
  template pull in copyrighted tracks.
- Trademarks/likeness: don't generate content impersonating real people or brands.
- Keep your API keys in n8n credentials, never in the repo.

**Bottom line:** the defaults keep you compliant. The two things that still get people in trouble
are (a) repointing the clip engine at content they don't own, and (b) running a firehose of
near-identical videos. Don't do either.
