# Setup

Target: your existing **self-hosted n8n**. Budget ≈ 30–45 minutes for the first run.

## 0. Prerequisites

- A running, reachable n8n instance (n8n ≥ 1.x). For webhook callbacks it must be reachable from
  the internet (or use the polling option — see §3).
- A Google account (for the config + log Sheet and the YouTube Data API).
- Social accounts you want to post to, connected through your chosen posting API.

## 1. Import the workflows

In n8n → **Workflows → Import from File**, import in this order (the engines call the shared one):

1. `workflows/00-subworkflows.json`  ← import first
2. `workflows/01-clipping.json`
3. `workflows/03-idea-engine.json`
4. `workflows/02-ai-generated.json`

After importing `00`, open each engine workflow and re-select the **Execute Sub-workflow** node's
target if n8n didn't auto-link it (node versions differ between builds — this is the one manual
re-link you may need).

## 2. Create the control sheet + log

1. Upload `config.csv` to Google Sheets (**File → Import**). Name the tab **`config`**.
2. Add two more tabs in the same spreadsheet: **`queue`** (topic queue the idea-engine fills) and
   **`log`** (dedupe + post history). Headers for each are in `config.csv`'s comment rows and in
   `scripts/seed_sheet.py`.
3. Copy the spreadsheet ID (from its URL) — you'll paste it into the Google Sheets nodes.

## 3. Credential checklist

Create these in n8n → **Credentials**. Only the ones for your chosen tier are required.

| Credential | Needed for | How to get it | Tier |
|------------|-----------|---------------|------|
| **Google Sheets OAuth2** | config / queue / log | n8n Google Sheets credential wizard | all |
| **YouTube Data API key** | CC clip finder (`search.list`) | Google Cloud Console → enable *YouTube Data API v3* → API key | all |
| **Posting API key** | multi-platform posting | upload-post dashboard (free tier) or Blotato | all |
| **LLM API key** | scripts, ideas, captions | Google AI Studio (Gemini, free) or Anthropic (Claude) | all |
| **Clipping API key** | Engine 1 clip step | OpusClip / Vizard / Klap dashboard (or self-host OpenShorts, no key) | Engine 1 |
| **TTS key** (optional) | Engine 2 voice | ElevenLabs (or self-host Kokoro, no key) | Engine 2 |
| **AI video key** (optional) | Engine 2 premium visuals | Veo via Google AI / HeyGen | Engine 2 premium |
| **Render key** (optional) | Engine 2 assembly | Creatomate / Shotstack (or FFmpeg via `scripts/`, no key) | Engine 2 |
| **Telegram bot token** (optional) | health alerts + quality gate | @BotFather → `/newbot` → token + your chat ID | recommended |

> **Never paste keys into the workflow JSON or commit them.** Use n8n credentials only. The
> workflows reference credentials by name, not value.

## 4. Point the workflows at your sheet + credentials

In each workflow, open the nodes marked with a 📝 sticky note and set:
- **Google Sheets nodes** → your spreadsheet ID + tab name.
- **HTTP Request nodes** (posting/clipping/video) → select the matching credential; the URL +
  body are pre-filled with placeholders like `={{ $json.videoUrl }}` — leave those, they're wired.
- **Config loader node** (first node after the trigger in each engine) → your spreadsheet ID.
  Everything else (niche, cadence, platforms, on/off) is read from the sheet at runtime, so you
  rarely touch the workflow again.

## 5. Dry run (do this before going live)

1. In the config sheet set `quality_gate = ON`, `engine1 = ON`, `engine2 = OFF`, and **one**
   platform in `platforms`.
2. Manually **Execute Workflow** on `01-clipping.json`.
3. It should: find one CC video → clip it → send you a Telegram preview (quality gate) → on your
   approval, post to the one platform → write a row to the `log` tab.
4. Confirm the post appears on the platform and the log row is correct.
5. Now set `quality_gate = OFF`, enable the platforms you want, turn `engine2 = ON`, and
   **activate** all four workflows (toggle *Active* in n8n). From here it runs on the schedule.

## 6. Verify you're truly hands-off

- Check the `log` tab fills on schedule.
- Trigger a deliberate failure (e.g., a bad key) once and confirm the **health alert** reaches
  Telegram/Slack — this is your safety net against silent death.
- Glance at the health channel every few days; otherwise leave it running.

## Troubleshooting

- **Sub-workflow node errors** → re-select the target workflow (see §1).
- **CC finder returns nothing** → broaden niche keywords, or lower `min_duration`, in config.
- **Clip/video job "stuck"** → your instance can't receive the webhook callback; switch that node's
  *completion mode* to **polling** (sticky note explains how).
- **Posts rejected** → the account isn't connected in your posting API dashboard, or you hit a
  per-platform rate limit (increase the stagger offset in config).
- **Node version mismatch on import** → recreate the flagged node fresh; the sticky note lists its
  settings.
