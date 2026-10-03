# Helper scripts

Optional utilities that support the workflows. They let you run the **free** (no-paid-API) path and
set up the sheets. Nothing here is required if you use the hosted services (Creatomate, a clipping
API, etc.) — these are the zero-cost fallbacks.

| Script | Purpose | Needs |
|--------|---------|-------|
| `burn_captions.sh` | Burn karaoke-style captions into a vertical video (FFmpeg fallback for the render step) | `ffmpeg` |
| `cc_attribution.py` | Build the Creative-Commons attribution line appended to clip posts | Python 3 |
| `seed_sheet.py` | Print / write the header rows for the `queue` and `log` tabs | Python 3 |
| `callback_listener.py` | Tiny local webhook receiver for testing clip/render callbacks | Python 3 |

## Typical free-path flow

1. Engine 2 produces a voiceover (Kokoro) + stock B-roll + caption text.
2. Instead of Creatomate, a host command concatenates B-roll to the voiceover length with FFmpeg,
   then `burn_captions.sh` burns the captions using the style in `../templates/caption-style.json`.
3. The finished `out.mp4` URL is handed to the shared posting subworkflow.

> To call these from n8n, use an **Execute Command** node (self-hosted n8n only) or run them on the
> host and expose the output file via a URL the posting API can fetch.

## Quick test

```bash
# attribution
python3 scripts/cc_attribution.py --title "Intro to Transformers" --author "Stanford Online" \
  --url "https://youtu.be/abc123"

# sheet headers
python3 scripts/seed_sheet.py

# caption burn-in (needs ffmpeg + a sample clip and subtitles)
bash scripts/burn_captions.sh sample.mp4 sample.ass out.mp4
```
