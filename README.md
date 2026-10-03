# Content Machine — fully-autonomous n8n short-form video system

A set-and-forget content pipeline that runs on your self-hosted **n8n**. You configure it once
(niche, sources, cadence, platforms) and it runs itself: it produces short-form video with two
self-feeding engines and auto-posts across your social accounts to maximize views.

```
                       ┌──────────────────────────────────────────────┐
                       │   config  (Google Sheet — the only thing you   │
                       │   touch: niche, sources, cadence, platforms)   │
                       └───────────────┬──────────────────────────────┘
                                       │
        ┌──────────────────────────────┴──────────────────────────────┐
        ▼                                                              ▼
┌───────────────────────────┐                        ┌──────────────────────────────┐
│ ENGINE 1 — CC CLIPPING     │                        │ ENGINE 2 — AI-GENERATED        │
│ 01-clipping.json           │                        │ 03-idea-engine.json (feeder)   │
│                            │                        │ 02-ai-generated.json           │
│ find Creative-Commons      │                        │ discover trend → script →      │
│ long-form in your niche →  │                        │ voice + visuals → assemble →   │
│ clip → transform/caption   │                        │ caption                        │
└──────────────┬─────────────┘                        └───────────────┬────────────────┘
               │                                                       │
               └───────────────────────┬───────────────────────────────┘
                                        ▼
                        ┌──────────────────────────────────┐
                        │ 00-subworkflows.json (shared)      │
                        │ dedupe → quality gate (opt) →      │
                        │ staggered multi-platform post →    │
                        │ log → health alert on failure      │
                        └──────────────────┬─────────────────┘
                                           ▼
            TikTok · YouTube Shorts · Instagram Reels · Facebook · X ·
            LinkedIn · Threads · Pinterest · Bluesky
```

## What this is (and isn't)

- **It is** a reliable, unattended *production + posting* machine: consistent output, dedupe,
  staggered scheduling, and failure alerts so it never dies silently.
- **It isn't** a money printer. No system guarantees views or revenue. Platforms actively throttle
  mass-produced, low-effort content. This project is engineered *around* those rules (Creative-
  Commons-only clip sourcing, a transform step, a variety injector, AI disclosure) — but what
  actually drives views is your niche + iteration, which stays your job. See
  [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md) and [`docs/PLAYBOOK.md`](docs/PLAYBOOK.md).

## The two engines

| Engine | Source | Copyright risk | Cost/video | Best for |
|--------|--------|----------------|------------|----------|
| **1 — CC Clipping** | Auto-found Creative-Commons long-form in your niche | Low (licensed to reuse, attribution auto-added) | ~$0 (free tier) → ~$0.50 | High volume, fast |
| **2 — AI-generated** | Self-discovered trending topics → original video | None (original) | ~$0.20 (stock+TTS) → ~$3–18 (AI video) | Original niches |

Run either or both — toggle per engine in the config sheet.

## Quickstart (≈30 min)

1. **Import workflows.** In n8n: *Workflows → Import from File* for each file in
   [`workflows/`](workflows/). Start with `00-subworkflows.json` (the others call it).
2. **Create the config sheet.** Upload [`config.csv`](config.csv) to Google Sheets. This is your
   control panel — fill in niche keywords, sources, cadence, target platforms, and the per-engine
   on/off switches.
3. **Add credentials.** Follow the checklist in [`docs/SETUP.md`](docs/SETUP.md): a Google/YouTube
   Data API key, your posting-API key (start with upload-post's free tier), an LLM key (Gemini has
   a free tier), and whichever clipping/video service you choose.
4. **Pick a budget tier.** [`docs/COSTS.md`](docs/COSTS.md) lays out three tiers with exact
   per-tool and per-video costs. Start on **Shoestring (~$0)** to prove it runs.
5. **Dry run.** With the quality gate ON, run the clip engine once, confirm one CC clip posts to
   one platform, then flip the gate OFF and enable both engines + more platforms.

## Repo layout

| Path | What's inside |
|------|---------------|
| [`workflows/`](workflows/) | Importable n8n workflow JSON (the 4 workflows above) |
| [`prompts/`](prompts/) | LLM prompt library — hooks, scripts, titles, captions, niche packs |
| [`templates/`](templates/) | Render template (Creatomate/Shotstack), caption style, brand kit |
| [`scripts/`](scripts/) | Helper scripts — ffmpeg caption burn-in, CC-attribution builder, callback |
| [`docs/`](docs/) | SETUP · COSTS · COMPLIANCE · PLAYBOOK |
| [`config.csv`](config.csv) | The one-time control sheet |

## Important

These are working **template** workflows wired for a typical stack. You supply your own API keys
and connected accounts, and you may need to match node versions to your n8n build. "Fully
autonomous" means no daily input — it still needs the one-time setup and an occasional glance at
the health alerts. Read [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md) before you go live: clipping is
restricted to Creative-Commons / licensed sources on purpose, to keep accounts safe.
