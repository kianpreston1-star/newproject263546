# Cloud AI

A free AI chat app that runs in the cloud. It can **search the web, read web pages, run code, create images and save files**. You don't need API keys or a powerful computer. Your browser only displays the page, and the AI runs on [Puter](https://puter.com)'s servers.

**Live app:** https://kianpreston1-star.github.io/newproject263546/ (this works once GitHub Pages is turned on; see below).

## How it's free

The app uses [Puter.js](https://docs.puter.com), which gives websites access to hundreds of AI models (GPT, Claude, Gemini, Gemma, DeepSeek, Grok and more) without API keys. Puter uses a "user pays" model:

- The first time you press **Start**, Puter creates a free guest account for you. You don't need an email address or card.
- Models marked **free** in the model menu (for example Gemma 4 31B, the default) cost nothing.
- Every account also gets a **free monthly allowance** for paid models. The sidebar shows how much you have left. If it runs out, switch back to a free model.

## Tools the AI can use

| Tool | What it does |
| --- | --- |
| Web search | Searches DuckDuckGo, falling back to Wikipedia. |
| Read web pages | Opens any link and reads the text. Puter's network proxy gets around browser CORS limits. |
| Run code | Runs JavaScript in a sandboxed Web Worker for exact maths, dates and data. |
| Create images | Generates pictures from a description. |
| Cloud files | Saves, reads and lists files in your free Puter cloud storage. |

You can turn each tool on or off in **Settings** (the gear icon). You can also add custom instructions and change the tool-step limit there.

## Put it online (one-time, about 1 minute)

Puter.js has to be served from a website. Opening `index.html` straight from your computer won't work. GitHub Pages hosts it for free:

1. On GitHub, open this repository and go to **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
3. Pick the branch that holds this code (`claude/determined-bardeen-vvrlm3`, or `main` after it has been merged) and the **/ (root)** folder, then click **Save**.
4. Wait about a minute. The app will then be live at https://kianpreston1-star.github.io/newproject263546/.

## Add it to your desktop

**Install it as an app (recommended).** Open the live link in **Chrome** or **Edge**, then click the install icon at the right end of the address bar. You can also open the ⋮ menu and choose **Cast, save and share → Install page as app** in Chrome, or **Apps → Install this site as an app** in Edge. It then opens in its own window and gets a desktop icon. If you're asked whether to create a desktop shortcut, say yes.

**Or use a shortcut file.** Copy `desktop-shortcut/Cloud AI.url` (Windows) or `desktop-shortcut/Cloud AI.webloc` (Mac) to your desktop. Double-clicking it opens the app in your browser.

## Files

- `index.html`: the whole app (HTML, CSS and JavaScript in one file).
- `manifest.webmanifest` and `icons/`: let browsers install the app with an icon.
- `vendor/`: bundled copies of [marked](https://github.com/markedjs/marked) (Markdown) and [DOMPurify](https://github.com/cure53/DOMPurify) (HTML sanitizing).
- `desktop-shortcut/`: desktop shortcut files for Windows and Mac.

Chats are saved in your browser's local storage on your own computer.
