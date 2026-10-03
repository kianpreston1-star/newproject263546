# Brand kit

Keep every video visually consistent so a channel looks like one creator, not a content farm.
Edit these values, then mirror them in `caption-style.json` and `creatomate-short.json`.

## Colors
| Role | Hex | Use |
|------|-----|-----|
| Caption text | `#FFFFFF` | Main burned captions |
| Caption outline | `#000000` | Readability on any background |
| Accent / highlight | `#FFD400` | Active word in karaoke captions, key numbers |
| Lower-third bar | `rgba(0,0,0,0.35)` | Behind captions |

## Fonts
- **Primary:** Montserrat (800–900 weight for hooks, 700–800 for captions). Free, bundled with most
  render tools; for FFmpeg, install it on the host (`scripts/burn_captions.sh` references the file).
- Fallback: Inter or Roboto Condensed.

## Layout & safe zones (9:16, 1080×1920)
- **Hook title:** top third, first ~2.5s only.
- **Captions:** bottom-center, but **above** the reserved bottom zone (≈320px) so TikTok/Reels UI
  doesn't cover them.
- **Right 180px:** keep clear of text (platform action buttons live there).
- **Logo/watermark (optional):** top-left or top-right corner, small, 60–70% opacity, inside the
  top safe zone.

## Audio
- Voiceover at full volume; music ducked to ~15–20%.
- Only licensed / royalty-free / platform-library music. No copyrighted tracks (see
  `../docs/COMPLIANCE.md`).

## Consistency rules
- One font system per channel.
- Same caption style across every video.
- Same intro hook placement.
- If you run multiple niches, give each its own brand kit (duplicate this file per channel).
