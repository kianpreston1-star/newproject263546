# Templates

Render + styling assets for Engine 2 (and the clip engine's transform step).

| File | Used by | Purpose |
|------|---------|---------|
| `creatomate-short.json` | `02-ai-generated.json` render node | Vertical 1080×1920 short: voiceover + B-roll + burned captions + music |
| `caption-style.json` | FFmpeg burn-in (`scripts/burn_captions.sh`) and clip transform | Caption font/size/position/colors |
| `brand-kit.md` | all | Colors, fonts, safe zones, logo placement — keep output consistent |

## How the render template works

`creatomate-short.json` is a Creatomate **source** you POST to their API (or adapt for Shotstack).
The n8n render node fills the `{{...}}` modification keys from the script output:

- `{{voiceover_url}}` — the TTS audio file (Kokoro/ElevenLabs output).
- `{{broll_1_url}} … {{broll_n_url}}` — stock/AI visuals, one per script beat.
- `{{caption_1}} … {{caption_n}}` — on-screen text per beat.
- `{{music_url}}` — background track matching `music_mood` (use a licensed/royalty-free library).
- `{{title}}` — the hook text shown in the first beat.

If you use the free path instead, `scripts/burn_captions.sh` + FFmpeg produce the same vertical
short from the same inputs (no Creatomate account needed) — slower, zero cost.

## Adapting

- **Different aspect ratio / platform:** change `width`/`height` (keep 9:16 for Shorts/Reels/TikTok).
- **Branding:** edit colors/fonts here and in `brand-kit.md`, and drop a logo element in the
  template's top corner within the safe zone.
- **More/fewer beats:** the render node loops beats; the template's caption + B-roll elements are
  duplicated per beat at runtime, so you don't need to hand-edit for length.
