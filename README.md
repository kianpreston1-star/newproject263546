# Cloud AI

A free AI chat app that runs in the cloud. It can **search the web, read web pages, run code, create images and save files**. You don't need API keys or a powerful computer. Your browser only displays the page, and the AI runs on [Puter](https://puter.com)'s servers.

## Install on Ubuntu (one command)

Open a terminal (**Ctrl+Alt+T**), paste this line and press Enter:

```bash
python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/determined-bardeen-vvrlm3/install-ubuntu.sh', '/tmp/install-cloud-ai.sh')" && bash /tmp/install-cloud-ai.sh
```

This uses Python, which every Ubuntu desktop includes, because newer Ubuntu releases no longer ship `wget` by default. The installer shows a ✔ for each step and checks that the app actually starts.

Cloud AI opens as soon as the install finishes. After that, open it in any of these ways:

- **Dock:** click the blue cloud icon in the dock (the bar on the left of the screen).
- **Search:** press the Super (Windows) key, type **Cloud AI** and press Enter.
- **Desktop:** double-click the **Cloud AI** icon on the desktop. Press Super+D to hide windows and see it. If Ubuntu says it isn't allowed to launch, right-click it and choose **Allow Launching**.

- **No sudo, no GitHub setup.** The installer copies the app to `~/.local/share/cloud-ai`. The icon starts a tiny local web server, which Puter.js needs because it won't run from a plain file, and opens the app.
- **Light on an older laptop.** The server only hands out a few static files, so it uses a few MB of RAM and no CPU while idle. It listens only on `127.0.0.1`, so nothing outside your computer can reach it.
- **Browser choice.** If Chrome, Chromium, Brave or Edge is installed, the app opens in its own window. Otherwise it opens in Firefox. If Firefox is already open and no Chrome-family browser is running, it reuses Firefox instead of starting a second browser, which saves memory.
- **Update:** run the same command again.
- **If something goes wrong:** the installer marks the failed step with a ✘. Copy what the terminal shows and ask for help. `~/.local/share/cloud-ai/cloud-ai --check` re-runs the check at any time.
- **Stop the background server:** `~/.local/share/cloud-ai/cloud-ai --stop`
- **Uninstall:** `bash ~/.local/share/cloud-ai/install-ubuntu.sh --uninstall`

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

## Optional: put it online for other devices

To use it on a phone or another computer as well, host it for free on GitHub Pages. Puter.js has to be served from a website, so opening `index.html` as a file won't work. The online copy is separate from the one installed on Ubuntu: each keeps its own chats and its own Puter guest account.

1. On GitHub, open this repository and go to **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
3. Pick the branch that holds this code (`claude/determined-bardeen-vvrlm3`, or `main` after it has been merged) and the **/ (root)** folder, then click **Save**.
4. Wait about a minute. The app will then be live at https://kianpreston1-star.github.io/newproject263546/.

### Add the online version to a Windows or Mac desktop

**Install it as an app (recommended).** Open the live link in **Chrome** or **Edge**, then click the install icon at the right end of the address bar. You can also open the ⋮ menu and choose **Cast, save and share → Install page as app** in Chrome, or **Apps → Install this site as an app** in Edge. It then opens in its own window and gets a desktop icon. If you're asked whether to create a desktop shortcut, say yes.

**Or use a shortcut file.** Copy `desktop-shortcut/Cloud AI.url` (Windows) or `desktop-shortcut/Cloud AI.webloc` (Mac) to your desktop. Double-clicking it opens the app in your browser.

## Files

- `index.html`: the whole app (HTML, CSS and JavaScript in one file).
- `manifest.webmanifest` and `icons/`: let browsers install the app with an icon.
- `vendor/`: bundled copies of [marked](https://github.com/markedjs/marked) (Markdown) and [DOMPurify](https://github.com/cure53/DOMPurify) (HTML sanitizing).
- `install-ubuntu.sh`: the Ubuntu installer and uninstaller.
- `linux/`: the launcher and the tiny local web server that the Ubuntu installer sets up.
- `desktop-shortcut/`: shortcut files for the online version on Windows and Mac.

## Made for older laptops

The app is written to stay light on modest hardware. It was tuned for a 2-core Intel i5 with 8 GB of RAM, a spinning hard drive and a 1366×768 screen:

- All the AI work happens in Puter's cloud. Your computer only shows the page.
- Chat history is saved in batches instead of after every step, which avoids constant small writes to a hard drive.
- Messages that are already on screen aren't re-processed when a new one arrives, so long chats stay smooth.
- Tool output from earlier turns is shortened, and very old turns are dropped from long chats before they're sent. Smaller requests mean faster answers, and less of your allowance used on paid models.
- The layout fits a 1366×768 screen, including inside a browser tab.

Chats are saved in your browser's local storage on your own computer.
