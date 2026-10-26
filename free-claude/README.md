# free-claude

Run [Claude Code](https://code.claude.com) on **free AI models**. A small router on your computer sends quick jobs to fast models and hard jobs to strong ones. When a provider's free allowance runs out, it switches to the next provider by itself.

```
Claude Code ──► free-claude router (127.0.0.1) ──► NVIDIA NIM ─┐ rate limited?
                 picks fast / main / smart         OpenRouter  ├ next one takes over
                                                   Google AI   │
                                                   Z.ai       ─┘
```

## Install on Ubuntu (one command)

Open a terminal, paste this line and press Enter:

```bash
python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/claude/keen-dirac-yp8pmx/free-claude/install.sh', '/tmp/free-claude-install.sh')" && bash /tmp/free-claude-install.sh
```

Run it as yourself, **not** as root or with `sudo`. It checks Python, your internet connection and Claude Code first, and installs Claude Code if it's missing. Then it asks for your free API keys, tests them and shows a ✔ for each step. Re-run the same command to update.

When it finishes, open a new terminal, go to a project folder and run:

```bash
claude-free
```

## Free keys (get at least one; more keys mean more free requests)

| Provider | Free allowance | Get a key |
| --- | --- | --- |
| **NVIDIA NIM** (recommended) | About 40 requests a minute and 10,000 a day: GLM-5.3, Kimi K2.6, DeepSeek V4.1 Flash, MiniMax M3.1 Flash, Nemotron 3 | [build.nvidia.com](https://build.nvidia.com): sign in and press **Get API Key** (it asks to verify a phone number) |
| **OpenRouter** | 50 requests a day on `:free` models, or 1,000 a day after a one-time $10 top-up | [openrouter.ai/keys](https://openrouter.ai/keys). Also allow free models in [privacy settings](https://openrouter.ai/settings/privacy); the installer tells you if they're blocked |
| **Google AI Studio** | Gemini Flash with a 1M-token memory; small daily limits per model | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **Z.ai** | GLM-4.7-Flash, no daily cap, one request at a time | [z.ai API keys](https://z.ai/manage-apikey/apikey-list) |

Add or change keys any time with `claude-free-router keys`. The keys are stored in `~/.config/free-claude/config.json`, which only your user can read. If you used the earlier one-provider OpenRouter script, the installer offers to reuse its key and removes its old `claude-free` alias.

## How it picks a model

Each request gets a tier, and the router remembers the choice for the whole task, so a job doesn't switch models halfway through.

| Tier | Used for | Tried first |
| --- | --- | --- |
| **Fast** | Claude Code's background jobs (titles, summaries), the Explore helper, and simple asks like "fix the typo in README", "what does this do?" or "commit and push" | GLM-5.3-Flash, Nemotron 3.5 Lightning, GLM-4.7-Flash |
| **Main** | Normal coding work | DeepSeek V4.1 Flash, GLM-5.3, MiniMax M3.1 Flash, Kimi K2.6 |
| **Smart** | Debugging, refactors, design, crashes and stack traces, long prompts, plan mode, and anything with "think hard" or "ultrathink" | GLM-5.3, Kimi K2.6, Gemini Flash, Nemotron 3 Ultra |

Claude Code tells the router what each request is for (main chat, helper agent, background job or summary). The router uses that, plus the words and length of your prompt. A short follow-up like "yes" or "go ahead" keeps the previous task's tier.

To choose the tier yourself, use `/model` in Claude Code: **Free · Auto** (the default), **Free · Smart** or **Free · Fast**.

## How switching works

- When a provider answers "rate limited" or "quota used up", the router rests that provider or model for as long as the provider says, and the next model on the list answers instead. NVIDIA's limit covers the whole account, so all NVIDIA models rest together. On OpenRouter, the daily free-model limit rests every OpenRouter model, while a single busy model rests on its own.
- If a whole tier is resting, the other tiers' models fill in, so a request only fails when everything is busy. Then Claude Code waits and retries by itself, or shows how long until a model is free.
- Models that are down, slow to start or that send an empty reply also rest briefly, with longer rests if they keep failing. A model with a lower output limit gets the same request again with a smaller one.
- If a conversation is too long for every model, the router asks Claude Code to compact it.
- The router keeps the NVIDIA and OpenRouter model lists up to date. Models they stop offering are skipped.
- Rest times survive restarts (`~/.local/state/free-claude/state.json`).

The status line at the bottom of Claude Code shows the tier and the model that answered, for example `free · main → deepseek-v4.1-flash (NVIDIA NIM) · swapped 1×`.

## Commands

| Command | What it does |
| --- | --- |
| `claude-free` | Starts Claude Code on free models. Any `claude` option works, for example `claude-free -p "explain this repo"` |
| `claude-free-router status` | Each provider and model: ready or resting, for how long and why, plus today's request counts |
| `claude-free-router logs -f` | Live log: each request's tier, the model that answered, and any swaps |
| `claude-free-router keys` | Add or change API keys (no restart needed) |
| `claude-free-router selftest` | Sends two tiny requests through the router |
| `claude-free-router restart` / `stop` | Restarts or stops the router. `claude-free` starts it again when needed |
| `claude-free-router update` | Downloads the newest router and restarts it |
| `claude-free-router uninstall` | Removes free-claude. Claude Code itself stays installed |

## Good to know

- **Bypass permissions.** `claude-free` starts Claude Code with `--permission-mode bypassPermissions`, so Claude edits files and runs commands without asking. Claude Code shows a one-time warning that you accept. Work in a git repository so you can undo. Passing your own `--permission-mode` overrides it, and so does `"permission_mode": "default"` in the config file.
- **Not Claude.** These are other companies' open models served through Claude Code. They're good, but weaker than Claude at long, careful agent work. Anthropic doesn't support pointing Claude Code at non-Claude models, so some features may misbehave. Claude Code's built-in web search needs Anthropic's servers and isn't available.
- **Privacy.** Free tiers may log or train on what you send (NVIDIA and Google say so; on OpenRouter it depends on your settings). Don't send secrets or code you can't share.
- **Limits change.** Free allowances and model lists change often. `claude-free-router status` shows what's working right now.
- **Light on an older laptop.** The router uses only the Python standard library and about 30 MB of memory, and all model work happens in the cloud. Nothing runs at login: `claude-free` starts the router in the background the first time you use it.

## Settings

`~/.config/free-claude/config.json` holds your keys, plus anything you change:

```json
{
  "keys": {"nvidia": "nvapi-…", "openrouter": "sk-or-…"},
  "tiers": {"main": ["nvidia:z-ai/glm-5.3", "openrouter:openrouter/free"]},
  "context_window": 128000,
  "max_output_tokens": 16000,
  "permission_mode": "bypassPermissions",
  "debug": false
}
```

- `tiers` replaces a tier's model list. Each entry is `provider:model`, where the provider is `nvidia`, `openrouter`, `gemini` or `zai`.
- `context_window` is when Claude Code compacts the conversation.
- `debug` logs the hints Claude Code sends with each request.

## Files

- `router.py`: the router and the `claude-free-router` commands, one file with no dependencies.
- `install.sh`: the installer.
- `tests/test_router.py`: tests that run the router against fake providers, with no keys or network needed. Run them with `python3 -m unittest discover -s free-claude/tests`.
