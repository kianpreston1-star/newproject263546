# AI Video Pipeline: Copy-and-Paste Build Prompts for Claude Code

This is a start-to-finish set of prompts for getting Claude Code to build an automated short-form video system. It finds ideas, researches them, writes and critiques scripts, records voiceovers, makes visuals, edits and renders videos, checks their quality, sends them to your phone for approval, posts them, and learns from the analytics.

It is built for **quality first**. Every stage has a quality check, and nothing gets posted until you approve it on your phone.

---

## How to use this

1. **Use Claude Code, not the normal Claude chat.** It has to write files and run code. You can use the terminal (`claude`), the desktop app, or claude.ai/code.
2. Start it in a **new empty folder or repo**.
3. Paste the **Master Prompt** first. Fill in the `[brackets]` before you send it. Answer Claude's questions, then **read SPEC.md and PLAN.md** and fix anything you don't like before any code gets written.
4. Then paste the **Phase prompts one at a time**. Test each phase before moving on. Running `/clear` between phases is fine, because everything lives in SPEC.md and PLAN.md.
5. Use the **Quality-tuning prompts** at the end whenever something isn't good enough.

**Don't rush Phase 2 (scripts).** If the scripts are weak, nothing else can save the video.

---

## Step 0: What you need before you start

| What | Why | Rough cost (check current prices) |
|---|---|---|
| Claude Code (Pro/Max plan) | Builds the system | Your existing plan |
| Anthropic API key (console.anthropic.com) | The pipeline uses Claude to write scripts and check quality. This is billed separately from your Claude subscription | ~$0.10–0.50 per video |
| ElevenLabs API key (a paid plan, needed for commercial use) | Voiceover | ~$20+/month |
| fal.ai **or** Replicate API key | AI images and AI video clips | ~$0.50–2 per video (standard), more in premium |
| Pexels API key | Free stock footage | Free |
| Telegram bot token (message @BotFather) and your chat ID | Approving videos from your phone | Free |
| Google Cloud project with **YouTube Data API v3** and **YouTube Analytics API** turned on, plus an OAuth client | Posting to YouTube and reading stats | Free |
| TikTok developer app (Content Posting API) and Meta developer app (Instagram), **or** an aggregator like Ayrshare | Posting to TikTok and Instagram | Free (official) or a monthly fee (aggregator) |
| A folder of **music you have the rights to** (Epidemic Sound, Artlist, YouTube Audio Library, etc.) and some sound effects | Background music and SFX | Varies |
| A machine with 4+ CPU cores and 8 GB+ RAM, Node.js 20+ and FFmpeg | Rendering. An old laptop works but is slow; a ~$10–20/month VPS is better for running it 24/7 | |

You don't need every key on day one. Claude will tell you which phase needs which key.

---

## Master Prompt (paste once, after filling in the brackets)

```
I want you to build me a production-quality, automated faceless short-form video system. The videos must be genuinely good: strong hooks, tight scripts, a consistent visual style, smooth motion, animated captions and properly mixed audio. Not generic AI slop. Quality beats volume every time.

Do NOT write any code yet. First read this whole brief and ask me any clarifying questions. Then write it up as SPEC.md (the full spec) and PLAN.md (a phased build plan with a checklist and a "definition of done" for each phase), and create CLAUDE.md with the project conventions. After that we'll build one phase at a time, and I'll test each phase before we move on.

## My channel
- Niche: [e.g. dark history mysteries most people have never heard of]
- Target viewer: [e.g. 18–35, curious, watches true crime and history content]
- Tone/personality: [e.g. calm, intriguing, slightly ominous storyteller, never cheesy]
- Platforms: [YouTube Shorts, TikTok, Instagram Reels]
- Length: [45–75 seconds, plus a 61–90 second option for TikTok, which only pays on videos over 1 minute]
- Videos per day: [1]
- Visual style: [e.g. cinematic, dark, moody oil-painting look, muted colours with gold highlights]
- Voice: [e.g. deep, calm British male narrator]
- Budget: [max $__ per video, $__ per month]
- My timezone: [e.g. Europe/London]
- Where it will run: [my Ubuntu laptop / a VPS]

## Tech stack (use this unless you have a strong reason not to, and tell me if so)
- TypeScript / Node.js 20+ for everything, in one repo
- Remotion for composing and rendering video (proper motion graphics and animated captions, far better than raw FFmpeg)
- FFmpeg for audio processing, loudness normalisation, previews and frame extraction
- SQLite for job state, history, costs and analytics
- Anthropic API (Claude) for ideas, research, scripts, critique and visual QA. Use the most capable current Claude model for writing and critique, and a cheaper one for simple tasks. Make the models configurable
- ElevenLabs for voiceover, using its timestamps endpoint for word-level timing (Whisper as a fallback)
- fal.ai (or Replicate) for AI images and AI video clips; the Pexels API for stock footage
- A grammY Telegram bot for approvals and alerts
- Official platform APIs for posting (YouTube Data API v3, TikTok Content Posting API, Instagram Graph API), each behind a common Publisher interface so I can swap in an aggregator like Ayrshare
- Docker Compose for deployment
- Every external provider sits behind an interface so I can swap models and services in config
- Before using any API, check its CURRENT documentation. Don't rely on memory for endpoints, field names, limits or prices

## The pipeline
Each stage is a resumable job step. State is stored in SQLite and files are cached under output/<video-id>/, so a failure never means starting over.

1. IDEAS
- Pull candidate topics from sources that fit my niche: Reddit, Google Trends, YouTube search for what's performing in the niche, RSS/news, plus Claude brainstorming.
- Score each idea 1–10 on curiosity gap, broad appeal, visual potential, originality compared with my past videos, and evidence that similar videos get views. Keep only ideas that score 8 or more.
- Never repeat a topic (dedupe against history with embeddings or fuzzy matching).
- Keep a topic backlog in the DB, and let me add my own ideas through Telegram.

2. RESEARCH (for factual niches)
- Use Claude with the web search tool to gather facts from several reliable sources. Store the sources and key quotes with the job.
- Every factual claim in the final script must trace back to a source. Cut anything that can't be verified, or clearly frame it as legend or rumour.

3. SCRIPT. This is the most important stage. Build it as a multi-pass writer:
- Pass 1: write 5 different hooks (the first sentence / first 1–2 seconds). Each hook must open a curiosity gap or interrupt the pattern immediately. Banned: "In this video", "Did you know", "Today we're going to", "Let's dive in", greetings, channel intros.
- Pass 2: score the hooks, pick the best one, then write the full script: hook, then one line of context, then escalating beats with a mini-cliffhanger every 8–10 seconds, then the payoff, then an ending that loops back to the start or gives people a reason to comment. Write for speech: short sentences, concrete specifics (names, dates, numbers), no filler, no clichés, no AI-sounding phrases ("delve", "tapestry", "in a world where", "buckle up", etc.).
- Pass 3: a separate critic pass scores the script 1–10 on hook strength, retention/pacing, clarity, specificity, emotional pull, originality, factual accuracy and platform fit, with specific line-level fixes. Rewrite and repeat, up to 3 rounds. Reject anything that averages below 8.
- Feed the writer a style bible, a file of my best past scripts as examples, and learnings.md (built from analytics in the learning-loop phase).
- Output: the script, 3 title options, description, hashtags, pinned comment, and a SHOT LIST. The shot list splits the script into scenes of 1.5–4 seconds. Each scene has the narration text, a visual description, a preferred source (AI video / AI image / stock), camera motion, any on-screen text, and a sound effect cue.

4. VOICE
- ElevenLabs with my chosen voice and tuned settings, with word-level timestamps.
- A pronunciation dictionary for tricky names. Normalise the loudness and trim dead air so the pacing stays tight.
- Scene timings come from the actual word timestamps, never from estimates.

5. VISUALS
- A style bible for each channel: art-style prompt suffix, colour palette, lighting, negative prompts, fonts. Every scene should look like it belongs in the same video.
- Generate each scene from the source named in the shot list. Two modes in config:
  - "standard": AI images (with motion added in Remotion) plus stock footage. Target ~$1–2 per video.
  - "premium": the same, but with AI video clips for the hook shot and 1–2 hero moments.
- Use Claude vision to check every image and clip against the scene description and the style bible (wrong subject, extra fingers, garbled text, off-style, low quality). Regenerate failures up to 2 times, then fall back to stock.
- For stock footage, search Pexels, use Claude vision on the candidates to pick the best match, and follow the licence and attribution terms.
- Never use copyrighted material: no film/TV clips, no other creators' content.

6. EDIT AND RENDER (Remotion, 1080x1920, 30fps)
- Cut on sentence or phrase boundaries, with a new visual every 1.5–4 seconds. Nothing on screen should sit still for more than about 3 seconds.
- Motion on stills: slow push-ins, pans, parallax, subtle zoom punches on key words. Vary it, so it's not the same Ken Burns move on every shot.
- Captions: animated word by word, with the active word highlighted, 1–3 words on screen at a time, and a bold font with an outline or shadow. Keep them inside the safe zone so the TikTok, Reels and Shorts buttons don't cover them. Use @remotion/captions if it fits.
- Optional on-screen text for key numbers and dates, a progress bar, and transitions that suit the style (nothing cheesy).
- Audio: the voice on top; background music from my licensed music/ folder (tagged by mood in a JSON file) and automatically ducked under the voice; subtle SFX (whooshes, risers, hits) on transitions and reveals from an sfx/ folder. Normalise the final mix to about -14 LUFS with true peak below -1 dBTP.
- Also render a small 720p preview for Telegram, which has a 50 MB upload limit for bots.

7. AUTOMATIC QUALITY GATE (runs before I see anything)
- Technical checks: duration in range, correct resolution and fps, no black or frozen frames, no audio clipping, captions in sync with the audio, file size.
- Claude visual review: extract a frame every ~1.5 seconds and make a contact sheet. Review them against the script and style bible, and score the hook (first 2 seconds), visual consistency, pacing and caption readability. On a fail, automatically fix or regenerate the weak scenes.
- Log every score so we can track quality over time.

8. HUMAN APPROVAL (Telegram)
- The bot sends me the preview, title, description, quality scores and cost.
- Buttons: Approve / Reject / Regenerate. If I reply with text feedback (e.g. "scene 4 is boring, the hook is weak"), apply it and re-render.
- Nothing is ever posted without my approval. Add an auto-approve option for videos above a score threshold, but keep it OFF by default.

9. PUBLISH AND SCHEDULE
- Post approved videos at the best times for each platform (configurable per platform, in my timezone), staggered across platforms.
- Format titles, captions and hashtags for each platform.
- Set the AI-generated / synthetic content disclosure flag wherever the API supports it.
- Handle OAuth token refresh, quotas, retries with backoff and idempotency, so nothing is ever posted twice.
- Unverified YouTube API projects and unaudited TikTok apps can only post PRIVATE videos until they pass review. Show a clear status message about this, and walk me through applying for review step by step.
- Hard daily caps per platform.

10. ANALYTICS AND LEARNING LOOP
- Pull stats at 24 hours, 72 hours and 7 days: views, average view duration, % viewed, likes, comments, shares, subscribers gained, and the retention curve where it's available.
- A weekly Telegram report: best and worst videos, and what they had in common (hook type, topic, length, visual mode).
- Claude keeps learnings.md updated with patterns backed by evidence, and it feeds into the idea and script stages. Don't overfit to one viral video.

## Non-negotiables
- Quality over quantity. Every video must be original (unique script, varied structure) so it doesn't break platform rules on mass-produced or "inauthentic" content.
- Only licensed music and assets. Store the licence info for every asset used.
- AI disclosure wherever it's required.
- Track the cost of every API call. Enforce per-video and monthly budget caps, and stop and alert me on Telegram if one is hit.
- All secrets in .env, never committed. Provide a .env.example.
- Every stage runs on its own from the CLI (e.g. `npm run stage -- script --video <id>`). Add `npm run make -- --topic "..."` for a full end-to-end run, and a `--dry-run` flag that skips posting.
- Clear logs and error messages. Failures alert me on Telegram.
- Tests for the core logic, with mocked providers.
- A README that explains setup step by step for a non-expert, including exactly how to get every API key.

Start now: ask me your clarifying questions, then write SPEC.md, PLAN.md and CLAUDE.md. Do not write any other code yet.
```

---

## Phase prompts (paste one at a time, test, then move on)

### Phase 1: Foundation
```
Read SPEC.md, PLAN.md and CLAUDE.md. Build Phase 1 (foundation): repo structure, TypeScript config, config loading (channel.yaml + .env, validated with clear errors), the SQLite schema and job state machine, the cost ledger, logging, provider interfaces with MOCK implementations of every provider, the CLI skeleton, .env.example and the README setup section.

Done when: `npm test` passes, and `npm run make -- --topic "test" --dry-run` runs through every stage using the mocks and creates output/<id>/ with placeholder files. Show me the output, tick off PLAN.md, commit, and stop. Don't start Phase 2.
```

### Phase 2: Ideas, research and scripts (spend the most time here)
```
Read SPEC.md, PLAN.md and CLAUDE.md. Build Phase 2: the idea sourcing and scoring, research with web search and stored sources, and the multi-pass script writer (5 hooks, then full script, then critic and rewrite rounds, then shot list). Put all prompts in separate editable files under prompts/, not buried in code.

Then generate 5 complete scripts for my niche. For each one, show me: the winning hook and the 4 that lost, the full script, the rubric scores from every round, the sources, the shot list, the title options and the cost.

Then STOP. I'll give feedback and we'll tune the prompts together until I'm genuinely happy with the scripts. Don't move on until I say so.
```

### Phase 3: Voice
```
Read SPEC.md, PLAN.md and CLAUDE.md. Build Phase 3 (voice): ElevenLabs with word-level timestamps, a Whisper fallback, the pronunciation dictionary, silence trimming and loudness normalisation.

Test: take 2 of the scripts I approved and generate each one with 3 different voice settings (stability/style/speed), so I can pick the best. Tell me the exact file paths, the cost, and which setting you'd choose and why. Commit and stop.
```

### Phase 4: Visuals
```
Read SPEC.md, PLAN.md and CLAUDE.md. Build Phase 4 (visuals): the style bible for my channel, shot list to asset generation through fal.ai/Replicate and Pexels, Claude vision checks with retries and fallbacks, licence tracking, and both "standard" and "premium" modes.

Test: run one approved script in standard mode. Make a contact sheet image of every scene in order, so I can judge consistency, look at it yourself, and tell me honestly what's weak. Report the cost per scene and in total. Commit and stop.
```

### Phase 5: Edit and render (where it starts looking like a real video)
```
Read SPEC.md, PLAN.md and CLAUDE.md. Build Phase 5 (Remotion edit and render): scene timing from word timestamps, varied motion on stills, word-by-word animated captions inside the platform safe zones, on-screen text for key facts, tasteful transitions, music ducking, SFX, -14 LUFS loudness, the final 1080x1920 render and the 720p preview.

Test: render one full video end to end. Then act as a harsh short-form video editor: extract a frame every 1.5 seconds, make a contact sheet, check the audio levels, and list the 10 biggest problems ranked by how likely each is to make a viewer swipe away. Fix the top problems IN THE PIPELINE (not just in this video), re-render, and show me before and after. Tell me how to open Remotion Studio to preview it myself. Commit and stop.
```

### Phase 6: Quality gate and Telegram approval
```
Read SPEC.md, PLAN.md and CLAUDE.md. Build Phase 6: the automatic quality gate (technical checks plus Claude visual review with auto-fix/regenerate) and the Telegram bot (preview, scores, cost, Approve/Reject/Regenerate buttons, free-text feedback that triggers a targeted re-render, adding ideas to the backlog, budget and error alerts).

Walk me through creating the bot with @BotFather and finding my chat ID. Test: run 3 videos end to end and send them to my Telegram. I'll test the approve, reject and feedback flows. Commit and stop.
```

### Phase 7: Publishing and scheduling
```
Read SPEC.md, PLAN.md and CLAUDE.md. Build Phase 7 (publishing): the YouTube publisher first, then TikTok and Instagram (official APIs, or the aggregator if I choose that), the per-platform scheduler with best-time slots in my timezone, daily caps, idempotency, token refresh, retries and AI-disclosure flags.

Walk me step by step through: creating the Google Cloud project and OAuth consent screen, creating the TikTok and Meta developer apps, and applying for YouTube API verification and the TikTok Content Posting audit (until those pass, posts are private-only). Test by uploading an approved video to YouTube as PRIVATE, then prove that running the same job again does NOT post it twice. Commit and stop.
```

### Phase 8: Analytics and learning loop
```
Read SPEC.md, PLAN.md and CLAUDE.md. Build Phase 8: pulling stats at 24h/72h/7d from each platform, storing them in SQLite, the weekly Telegram report, and the learnings.md updater that feeds proven patterns into the idea and script prompts (with guards against overfitting to one video). Add a simple command to print a performance table of every video. Test with real data if I have any, otherwise with realistic mock data. Commit and stop.
```

### Phase 9: Deploy and run it 24/7
```
Read SPEC.md, PLAN.md and CLAUDE.md. Build Phase 9 (deployment): Docker Compose (with Chrome/FFmpeg for Remotion), restart policies, a scheduler that runs the daily pipeline, a daily SQLite backup, health-check pings and failure alerts to Telegram, log rotation, cleanup of old render files, and one command to update.

Give me exact step-by-step instructions to deploy it on [my Ubuntu laptop / a VPS — recommend one with enough CPU and RAM for Remotion]. Add a runbook to the README: how to check it's running, how to pause and resume posting, how to change the niche or style, and the common errors with their fixes. Commit and stop.
```

---

## Quality-tuning prompts (use any time)

**When a video feels boring**
```
Review the last rendered video like a harsh YouTube Shorts editor. Extract a frame every second and the transcript with word timestamps. Find the exact moments a viewer is most likely to swipe away and explain why. Rank the 10 biggest problems by impact and fix the top 3 in the pipeline so every future video benefits, not just this one. Re-render and show me before and after.
```

**When retention drops at a certain point**
```
My retention drops sharply at around [0:08]. Look at what happens in the script, visuals and audio at that point across my last 10 videos, find the pattern, and change the script and edit stages to fix it. Explain what you changed and why.
```

**When the scripts sound like AI**
```
The scripts still sound AI-written. Here are 3 scripts from creators in my niche whose style I like: [paste them]. Work out exactly what makes them work (sentence length, rhythm, specificity, how they build tension), update the style bible and writer prompts, and show me before and after on 3 new topics.
```

**When the visuals look cheap or inconsistent**
```
The visuals look [cheap / inconsistent / too generic]. Improve the style bible and image prompts. Generate 3 distinct style options for the same 3 scenes, put them on one contact sheet, and let me choose. Then apply my choice to the style bible.
```

**When costs are too high**
```
Show me the cost breakdown per stage for my last 10 videos. Suggest changes that cut cost by at least 30% without hurting quality (cheaper models for simple steps, caching, fewer regenerations, smarter use of premium clips), with the expected saving for each. Implement the ones I approve.
```

**Adding a second channel**
```
Add support for multiple channels. Each channel gets its own channel.yaml (niche, voice, style bible, schedule, platform accounts, budget) and its own learnings.md, with shared code. Create a second channel for [new niche] and run one test video through it.
```

---

## Honest expectations

- **Build time:** a few evenings to a couple of weeks, mostly spent tuning scripts and visuals until they're good.
- **Running cost (1 video a day):** roughly $30–90/month in standard mode, plus ElevenLabs and any server. Premium mode with AI video clips costs more. Your budget caps keep it under control.
- **Posting will be private-only at first** until YouTube and TikTok approve your API app. Apply early. An aggregator gets around this, but costs a monthly fee.
- **Results take months.** Even good channels usually need consistent posting for a while before anything pays. Platform rules on AI and mass-produced content keep changing, so keep the human approval step and check each platform's monetisation rules.
