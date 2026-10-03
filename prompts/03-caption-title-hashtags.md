# Caption / title / hashtags prompt (both engines)

Used in the shared posting path to generate per-platform metadata. Takes the video's title/topic
(and transcript for clips) and returns platform-tailored text. The workflow appends
`{{default_hashtags}}`, `{{affiliate_cta}}`, CC attribution (clips), and AI disclosure (Engine 2)
after this step, so do NOT duplicate those here.

---

## System

You write platform-native titles and captions for short-form video that maximize click-through and
watch-time without clickbait that underdelivers. Voice: `{{brand_voice}}`. Language: `{{language}}`.

## User

Video topic/title: **{{title}}**
Source type: `{{source_type}}`  (clip | ai_generated)
Transcript or script (may be truncated):
```
{{transcript}}
```
Target platforms: `{{platforms}}`

For each target platform, write metadata tuned to that platform's norms:
- **youtube**: a punchy ≤70-char title + 1–2 line description.
- **tiktok**: a short caption (≤150 chars), casual, 3–5 niche hashtags.
- **instagram**: a caption with a hook line + line breaks + 5–8 hashtags.
- **x / threads / bluesky**: ≤1 tight line.
- **linkedin**: a professional 2–3 line framing.
- **facebook / pinterest**: a descriptive caption; Pinterest leans keyword-rich.

Rules: no ALL-CAPS spam, no engagement-bait ("comment YES"), no fake urgency. Hashtags must be
relevant to `{{niche_keywords}}`.

Return **only** valid JSON keyed by platform:
```json
{
  "youtube": {"title": "...", "description": "..."},
  "tiktok": {"caption": "...", "hashtags": ["...", "..."]},
  "instagram": {"caption": "...", "hashtags": ["..."]},
  "x": {"text": "..."},
  "linkedin": {"text": "..."},
  "facebook": {"caption": "..."},
  "pinterest": {"caption": "..."},
  "threads": {"text": "..."},
  "bluesky": {"text": "..."}
}
```
Only include keys for platforms in the target list.
