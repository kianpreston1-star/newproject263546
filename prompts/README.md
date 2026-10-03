# Prompt library

These are the prompts the LLM nodes in the workflows use. Placeholders in `{{double_braces}}` are
filled at runtime from the config sheet (e.g. `{{niche_keywords}}`, `{{brand_voice}}`) or from the
current item (e.g. `{{topic}}`, `{{transcript}}`).

| File | Used by | Purpose |
|------|---------|---------|
| `01-idea-discovery.md` | `03-idea-engine.json` | Brainstorm fresh, specific topics to fill the queue |
| `02-script-generation.md` | `02-ai-generated.json` | Turn a topic into a short-form script + on-screen text (with variety injector) |
| `03-caption-title-hashtags.md` | both engines | Per-platform title, caption, hashtags, disclosure, CTA |
| `hooks-library.md` | reference | Hook styles the variety injector rotates through |
| `niche-packs/` | swap per channel | Niche-specific tone, examples, do/don't — point the nodes at one pack |

## How variety is injected (anti-"templated content")

`02-script-generation.md` takes a `{{variety_seed}}` that the workflow sets to a random hook style
(from `hooks-library.md`) + a random structure + random pacing each run. This keeps outputs from
looking mass-produced, which is what gets channels throttled (see `../docs/COMPLIANCE.md`).

## Swapping packs as you learn

After ~20–30 posts, copy your best-performing hook styles into the active niche pack and narrow the
examples. The prompt files are plain Markdown — edit freely; the workflows re-read them each run if
you store them in the sheet, or re-paste into the LLM node if you keep them inline.
