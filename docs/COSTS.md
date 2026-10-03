# Costs

Everything here is **pay-for-what-you-use** on top of your existing self-hosted n8n (which is
free). Prices are list prices as of **2026** and move often — treat them as planning figures and
confirm on each provider's pricing page before committing. Links at the bottom.

## The three tiers

Pick a tier in the config sheet by choosing which services you wire up. You can switch tiers later
by swapping a single node — nothing else changes.

| Component | **Shoestring (<$30/mo)** | **Starter ($30–60/mo) ◀ recommended start** | **Serious ($100–400/mo)** |
|-----------|--------------------------|----------------------------------------------|----------------------------|
| n8n | self-host (you already have it) | self-host | self-host |
| Multi-platform posting | upload-post free (10 posts/mo) | upload-post $24/mo *or* Blotato $29/mo | Blotato $29–97/mo |
| CC finder (clip source) | YouTube Data API — free quota | YouTube Data API — free quota | YouTube Data API — free/raised quota |
| LLM (scripts, ideas, captions) | Gemini free tier | Gemini or Claude (cents per script) | Claude (cents per script) |
| Clipping engine | OpenShorts (free, self-host) *or* Klap pay-as-you-go | OpusClip ~$15–29/mo *or* Vizard ~$30/mo | Clipping API, higher volume |
| AI video (visuals) | stock (Pexels/Pixabay, free) + Kokoro TTS (free) + FFmpeg | Veo 3.1 Lite credits (~$0.40 per 8s) | Veo 3.1 Standard (~$3.20/8s) *or* HeyGen $99/mo |
| **Rough per-video cost** | **~$0 clip / ~$0.20 generated** | **~$0.50–2** | **~$3–18** |

## Per-unit prices (the pieces)

### Multi-platform posting
- **upload-post** — free tier 10 uploads/mo; unlimited from **$24/mo**; whitelabel from $50/mo;
  ~22 platforms. Best for prototyping free before you commit.
- **Blotato** — flat **$29/mo** (Starter, 20 accounts) regardless of posting volume; $97/mo
  (Creator, 40 accounts); $499/mo (Agency). 9 platforms, strong n8n community support, clean media
  upload. Best when volume grows and you want a flat bill.

### Clipping engine
- **OpenShorts** — open-source (MIT), self-hostable, **free** (you pay only compute). Best zero-cost
  option; more setup.
- **Klap** — pay-as-you-go API: ~$0.44 to ingest a video + ~$0.32 per generated short + ~$0.48 per
  export ≈ **~$1.24 per finished clip**. Completion by polling.
- **OpusClip** — Pro includes limited API access (capped ~300 credits/mo), signed webhooks, an MCP
  connector, and an official Zapier integration. Plans roughly $15–29/mo.
- **Vizard** — API + webhook (or 30s polling) on paid plans; an n8n template exists. ~$30/mo range.

### LLM (scripts, ideas, captions, titles)
- **Gemini** — generous free tier; good enough to start.
- **Claude** — a few cents per script at most; best quality for hooks/scripts.

### AI video (only used by Engine 2's premium branch)
- **Stock + TTS branch (cheap):** Pexels/Pixabay stock video (free API), Kokoro TTS (free,
  self-host) or ElevenLabs (paid, better voices), assembled with Creatomate/Shotstack or FFmpeg.
  Effective cost **~$0.10–0.50 per video**.
- **Veo 3.1 Lite** — ~$0.05/sec → **~$0.40 per 8-second clip**. Cheapest paid motion video.
- **Veo 3.1 Standard (native audio)** — ~$0.40/sec → **~$3.20 per 8s**. Full Veo 3 can run ~$6/8s
  and, with 3–4 prompt retries, effectively $18–24 for one usable clip — budget for retries.
- **HeyGen** — API from **$99/mo**; ~$7–18 per finished video depending on resolution. Presenter/
  avatar style.
- **Creatomate / Shotstack** — render/assembly APIs; Creatomate ~$41/mo, Shotstack has a free tier.
  FFmpeg (free) is the fallback renderer (see `scripts/`).

## Worked monthly examples

- **Prove it works — ~$0/mo:** self-host n8n + upload-post free + OpenShorts + Gemini free +
  stock/Kokoro/FFmpeg. Caps at ~10 posts/mo (upload-post free). Good for a 1–2 week trial.
- **Daily posting, 1 niche — ~$50/mo:** upload-post $24 + OpusClip ~$20 + Gemini/Claude (~$5) +
  stock/TTS visuals. ~1–3 posts/day across platforms.
- **Multi-channel, AI video — ~$250/mo:** Blotato $29 + clipping API + Veo 3.1 Standard credits
  (~$150 at a few videos/day) + Claude + ElevenLabs. Several niches in parallel.

## Cost-control rules baked into the workflows

- **Dedupe** so you never pay to clip/generate the same thing twice.
- **Cadence cap** in config limits videos/day → caps spend.
- **Cheap branch is the default** for Engine 2; the premium AI-video branch is opt-in per the
  config sheet, so you don't burn Veo credits by accident.
- **Health alert** fires if a paid API errors, so you catch a runaway/broken job fast.

## Sources
- upload-post pricing: https://www.upload-post.com/ · Blotato pricing:
  https://www.plugkit.co/blog/blotato-pricing-api-alternatives/
- Clipping API comparison: https://reap.video/reports/state-of-top-ai-video-clipping-tools-2026 ·
  OpenShorts: https://www.openshorts.app/
- AI video pricing: https://fluxnote.io/guides/ai-video-model-pricing-comparison-2026 ·
  https://devtk.ai/en/blog/ai-video-generation-pricing-2026/ · HeyGen:
  https://www.heygen.com/api-pricing
- n8n pricing (if you ever move off self-host): https://www.cloudzero.com/blog/n8n-pricing/
