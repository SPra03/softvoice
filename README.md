# softvoice

**Talk to Claude Code and Codex, and hear them talk back. Everything stays on your Mac.**

![macOS Apple Silicon](https://img.shields.io/badge/macOS%2014%2B-Apple%20Silicon-black?logo=apple)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
[![PyPI](https://img.shields.io/pypi/v/softvoice?color=blue)](https://pypi.org/project/softvoice/)
![On-device](https://img.shields.io/badge/your%20voice%20%26%20text-never%20leave%20your%20Mac-blue)
[![CI](https://github.com/SPra03/softvoice/actions/workflows/ci.yml/badge.svg)](https://github.com/SPra03/softvoice/actions/workflows/ci.yml)

<p align="center"><img src="https://raw.githubusercontent.com/SPra03/softvoice/main/docs/images/demo.gif" width="720" alt="45 seconds, no cuts: a prompt is dictated into Claude Code in Terminal, the live transcript shows in the pill, Enter pastes and sends it, and the reply is read aloud while the pill shows the sentence being spoken and a thin underline follows it in the terminal"></p>

<p align="center"><sub>45 seconds, no cuts: a prompt dictated into Claude Code, sent with Enter, and the reply read aloud while the pill and a thin underline follow along.</sub></p>

An open-source, offline tool to Converse with your coding agent. Tired of reading claude/codex
outputs all day long, I made this tool to listen instead of reading my claude/codex outputs. Its
just like having a conversation, without spending a dime. Drag the pill anywhere to place and use
it across apps.

Under the hood: [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) by Kyutai is the voice,
[Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) by NVIDIA is the ear,
and the agents' own hooks are the plumbing. No MCP server, no wrapped terminal, nothing about how
you work changes.

Apple Silicon Mac, macOS 14 or newer. MIT licence. Early, and in daily use by its author.

## What it does

Two things, both on device.

### Dictation: you talk, your agent gets text

- **Click the mic or press the talk key.** Option+Space, or any key you choose. Speak for as
  long as you like.
- **Watch the words land.** Sentences appear in the pill as you say them, so you can check them
  before they go anywhere.
- **Enter pastes, Escape discards.** The text goes into whatever has focus: Claude Code, Codex,
  or any other app.

### Speech: your agent talks, you listen

- **Replies read themselves.** When Claude Code or Codex finishes a turn, the reply is spoken.
  The pill shows the sentence being read and a thin underline follows it in the terminal.
  Nothing to press.
- **Read anything.** Select text in any app and click the speaker. It reads the selection.
- **Stop whenever you like.** Tap the talk key or click the speaker.

## Features

- **Offline.** Everything runs on your Mac, so it works offline.
- **Private.** No audio or data ever leaves the machine.
- **Lightweight.** Lighter than a handful of browser tabs (max 2.4 GB). The CPU sits at
  0% until you talk: under 1% while you dictate; 27 seconds of speech transcribe in 0.6 s.
- **Multilingual.** Understands 25 European languages, speaks 7.
- **Auto reply.** Replies are read aloud the moment the agent finishes. Hands-free
  mode then opens the mic for your next turn.
- **Multi-voice.** 27 voices, or clone your own from a short WAV.

## Set up

Five steps, about ten minutes, most of it the model download. [uv](https://docs.astral.sh/uv/)
does the Python work.

### 1. Install

```bash
brew install uv
uv tool install softvoice
```

(Or the newest commit straight from GitHub: `uv tool install git+https://github.com/SPra03/softvoice`.)

### 2. Download the models and grant the permissions

```bash
softvoice setup
```

This fetches the two models once (Pocket TTS, about 230 MB; Parakeet, 2.5 GB) and then makes
macOS ask for the three permissions below in one go, so nothing interrupts you later. The output
looks like this, with your own download times:

```
config: /Users/you/.softvoice/config.toml
Pocket TTS (english, voice alba): about 230 MB the first time
  ready in 40s
Parakeet (mlx-community/parakeet-tdt-0.6b-v3): 2.5 GB the first time
  ready in 190s
Permissions (granted to the app this terminal belongs to):
Microphone: opened
Input Monitoring: granted (push-to-talk key)
Accessibility: granted (pasting)
Next: `softvoice install` adds the hooks, then `softvoice app --hands-free` starts the pill.
```

macOS grants permissions to the app that owns the terminal you ran `setup` from (Terminal, iTerm,
the Claude desktop app, VS Code), not to softvoice itself. When a prompt appears, click **Open
System Settings** and switch that app on. A line that says NOT granted has the same fix, and
nothing needs a restart.

| permission | needed for | where |
| --- | --- | --- |
| Microphone | listening | asked the first time the mic opens; Privacy & Security > Microphone |
| Accessibility | pasting your words into the prompt; reading the page for the underline | Privacy & Security > Accessibility |
| Input Monitoring | seeing the talk key and scroll events | Privacy & Security > Input Monitoring |

<p align="center"><img src="https://raw.githubusercontent.com/SPra03/softvoice/main/docs/images/accessibility.png" width="480" alt="System Settings, Privacy and Security, Accessibility: the Claude desktop app and python3.12 switched on"></p>

<p align="center"><sub>Accessibility on the author's Mac after setup: the Claude desktop app, which owns the terminal <code>setup</code> ran from, and <code>python3.12</code>, which the login item in step 4 runs under.</sub></p>

### 3. Hook into Claude Code and Codex

```bash
softvoice install
```

This writes three hooks (`Stop`, `Notification`, `UserPromptSubmit`) into `~/.claude/settings.json`,
keeping a backup next to it, and into `~/.codex/hooks.json` if `~/.codex` exists. Sessions that are
already open keep their old settings: start a new Claude Code session, and in Codex run `/hooks`
once to trust them.

### 4. Start the pill

```bash
softvoice autostart on
```

The pill appears at the bottom right and comes back at every login, with no terminal left open.
It runs under Python rather than your terminal, so macOS asks for the same permissions once
more, this time for `python3.12`. Grant them and they stick.

<p align="center"><img src="https://raw.githubusercontent.com/SPra03/softvoice/main/docs/images/pill-idle.png" width="95" alt="The pill at rest: a coral mic and a grey play button"></p>

### 5. Try it

Ask Claude Code anything. When it finishes the turn you hear the reply, and the pill shows the
sentence being spoken. Then tap **right Option** (or click the mic), say what you want next, and
press **Enter**: your words land in the prompt, ready to send.

<p align="center"><img src="https://raw.githubusercontent.com/SPra03/softvoice/main/docs/images/pill-dictating.png" width="398" alt="A dictation session: the live transcript in the pill, with a cross to discard and a tick to paste"></p>

Later, `uv tool upgrade softvoice` upgrades. Everything softvoice owns lives in `~/.softvoice`.
It needs about 4 GB of disk for the models and the Python environment, and about 2 GB of memory
while running. The models load once at start; idle, it uses no CPU.

### If something is off

| symptom | what to check |
| --- | --- |
| nothing is spoken | `softvoice status` shows the daemon and `softvoice log` the hook calls. Hooks are read when a session starts, so only new Claude Code sessions speak. |
| no pill | `softvoice autostart` shows the login item; **Show pill** in the menu bar brings back a hidden one; `~/.softvoice/app.log` says why it did not start. |
| the talk key does nothing | Input Monitoring for the app that runs the pill: `python3.12` under the login item, your terminal's app otherwise. |
| your words are not pasted | Accessibility for the same app. Meanwhile the text is on the clipboard, so ⌘V works. |
| no underline on the page | the app has to start after Accessibility is granted (under the login item it restarts itself). Some apps expose no text; the app log says so. |
| the mic hears nothing | Microphone for that app, under Privacy & Security > Microphone. |

### Uninstall

```bash
softvoice uninstall         # removes the hooks
softvoice autostart off     # removes the login item and stops the app
uv tool uninstall softvoice
rm -rf ~/.softvoice         # config and logs
```

The models stay in Hugging Face's cache: delete `~/.cache/huggingface/hub/models--kyutai--pocket-tts-without-voice-cloning`
and `~/.cache/huggingface/hub/models--mlx-community--parakeet-tdt-0.6b-v3` to get the space back.

## Everyday use

The pill has two buttons. The **mic** on the left is you talking to the agent; the **speaker** on
the right is the agent talking to you. Exactly one thing on the pill is coral at any time, and it
is the thing to tap next. Most of the time you will not touch the pill at all: replies read
themselves, and the **talk key** does the rest.

The talk key is **right Option** by default: the ⌥ key to the right of the space bar, chosen
because nothing else uses it on its own. Prefer a combination? One line in the config:
`hotkey = "alt+space"` (or `ctrl+shift+d`, `fn+space`, ...). A combination is swallowed, so the
app in front never sees it.

### The mic: talking to your agent

There are three ways to talk. All of them end the same way: what you said is transcribed on your
Mac and pasted into the prompt where your cursor is, ready for you to read, edit and send.

#### Dictate: tap the key, or click the mic

For anything longer than a sentence. The pill grows to the left into **waveform · live text ·
✕ · ✓** and you talk for as long as you like. Your words appear in the pill as you go: sentences
you have finished are white, the one still forming is grey, and the line slides so the newest
words stay in view. Each pause of `dictation_pause_ms` (0.7 s) commits a sentence; the one you are
still saying is re-transcribed about once a second so you can watch it form.

- **Done talking**: press **Enter**, tap the key again, or click **✓**. Everything is pasted into
  your prompt in one piece. Read it, fix a word if you need to, and press Enter again to send.
- **Send without touching the keyboard**: end with "send it" (`send_words`), and it pastes and
  presses Enter for you. **Auto-send** in the menu does that every time.
- **Changed your mind**: press **Escape**, click **✕**, or say "cancel" or "never mind"
  (`cancel_words`). Nothing is pasted.
- **Walked away**: after `dictation_silence_s` (8 s) of silence the session finishes by itself.

Enter and Escape are only taken while a dictation session is open, and only on their own: Cmd,
Ctrl and Option combinations still reach your app. The preview lives in the pill rather than in
the prompt on purpose: live text keeps revising itself, and the prompt gets one clean paste.

#### Push-to-talk: hold the key, speak, let go

For a quick one-liner. Hold the key, say it, release: the take is transcribed and pasted where
your cursor is, without a session, a preview or any buttons. Presses shorter than
`tap_threshold_ms` (350 ms) count as a tap, longer ones as a hold.

#### Hands-free: a conversation

Turn it on in the menu, with `softvoice app --hands-free`, or with `hands_free = true`. Each time
the agent finishes speaking a reply, the mic opens by itself:

1. a short high beep: the mic is open
2. you talk; Silero VAD waits until you pause for `end_silence_ms` (0.9 s)
3. a short low beep: the mic is closed and Parakeet transcribes
4. the text is pasted into the agent's prompt, where you can read and edit it, then you press Enter

"Send it" and **Auto-send** (`auto_submit = true`) work here too, so a whole exchange can go by
without your hands leaving the coffee. Say nothing for `listen_timeout_s` (10 s) and the mic
closes. "Cancel" discards a take. Hold the talk key at any moment to interrupt the speaker and take
over. If you typed a prompt yourself, or interrupted the speaker, the mic stays closed.

#### Where your words go

Dictation and push-to-talk paste into whatever app is in front, because you started them on
purpose: the Claude Code prompt in a terminal, the desktop app, a text field anywhere. Hands-free,
where the mic opens by itself, is more careful: it pastes only into terminals and agent apps
(`paste_targets`) or an app you have dictated into before, and otherwise puts the text on the
clipboard and tells you.

Without the pill, from a terminal: `softvoice listen` (hold the key, speak, release) and
`softvoice listen --hands-free`. `--auto-submit` presses Enter for you; `--no-paste` only prints.

### The speaker: hearing your agent

#### Replies read themselves

Nothing to press. When an agent finishes a turn, its Stop hook calls `softvoice hook`, which hands
the reply to a small daemon (started on demand, kept warm) that cleans it up and speaks it:

- the whole turn is spoken, not just the last paragraph: every text block of at least
  `interim_min_chars` (200) since your message, so a long answer written before a tool call is not
  lost, while short progress notes between tool calls are skipped
- code blocks, tables, URLs and long paths are dropped or shortened: look at the screen for those
- markdown is flattened; bullets become sentences so the voice pauses
- anything that looks like a key or token is replaced with "redacted"
- the whole reply is spoken, however long; set `max_chars` to cut long replies at a sentence
  boundary with "More on screen."
- permission prompts are spoken too, so you hear when the agent is waiting for you

#### While it speaks

<p align="center"><img src="https://raw.githubusercontent.com/SPra03/softvoice/main/docs/images/pill-speaking.png" width="368" alt="The pill while a reply is read aloud: the words already spoken are white, the rest grey, and a coral stop button"></p>

- **Stop it**: tap the talk key, or click the speaker (the coral stop button). Sending a new
  prompt stops it as well.
- **Follow along in the pill**: it shows the sentence being spoken on one line. The words already
  said and the current one are white, the rest grey, and long sentences slide left so the current
  word stays in view. The daemon speaks one sentence at a time and learns its own speaking rate,
  so the timing stays close.
- **Follow along on the page**: a thin light grey underline is drawn under that sentence in the
  front window, line by line, found through macOS accessibility. It works where the app exposes
  its text: the Claude desktop app, Terminal, VS Code and most native apps. The underline follows
  the page: every scroll event makes it re-read its position at once, and a slow safety read twice
  a second covers keyboard scrolling and scrollbar drags. When there is nothing to underline, the
  app log says why. Turn it off with the pill's menu or `highlight_on_page = false`.

#### While it is quiet

- **Hear it again**: click the speaker and the last reply is read once more.
- **Read anything**: select text in any app, click the speaker, and it reads the selection.
- **Mute**: in the pill's menu, the menu bar, or `softvoice mute`. The speaker icon is slashed
  while muted; `softvoice unmute` or the same menu brings the voice back.
- **Change the voice**: `softvoice voice jane` picks one of the predefined voices
  (`softvoice voices` lists them), or point `voice` in the config at a short WAV of your own.

From a terminal:

```bash
softvoice say "hello there"      # speak anything
softvoice stop                   # shut up
softvoice mute / unmute          # stay silent across turns
softvoice voice jane             # try another voice (see `softvoice voices`)
softvoice status | log | restart
```

### The pill and the menu bar

A small dark glass pill (44 points tall) floats above every window, bottom right by default.
Drag it anywhere; it remembers the spot. Clicking it never steals focus, so your cursor stays in
the prompt. It uses one accent colour, and the accent always means "live": the mic is coral at
rest (talking is the next thing to do) and becomes a live coral waveform while it listens; the
speaker is a coral stop button while the voice talks and a grey play button when it is quiet,
slashed when muted. Whenever text shows, the capsule becomes a rounded rectangle, and the text is
a single line that scrolls, newest words at the right.

**Press and hold** either button, or right-click, for the options: Hands-free, Auto-send, Mute,
Underline, Voice, Hide pill, config file, Quit. `panel = false` in the config turns the pill off.

The menu bar gets one small waveform, the same in every state (the pill is where state shows);
`menu_bar_icon = false` hides it. Its first line says what softvoice is doing right now, and the
menu has **Hide pill** / **Show pill**, **Talk**, **Stop speaking**, **Mute**, **Hands-free** and
**Auto-send**, the config file, and Quit.

<p align="center"><img src="https://raw.githubusercontent.com/SPra03/softvoice/main/docs/images/menu-bar.png" width="234" alt="The menu bar menu: a status line, Talk, Stop speaking, Mute, Hands-free, Auto-send, Hide pill, Open config file, Quit softvoice"></p>

#### Running without a terminal

`softvoice autostart on` registers the app as a macOS login item: it starts when you log in, needs
no terminal, and comes back by itself if it ever crashes (not after you quit it on purpose).
`softvoice autostart off` removes the login item and stops the app; `softvoice autostart` shows
the state. The app's output goes to `~/.softvoice/app.log`. By hand, `softvoice app --hands-free`
starts the same app from a terminal.

Only one copy of the app runs at a time: `softvoice app` while it is already running just shows
the pill of the running one. **Hide pill** tucks the pill away while the key, the voice and the
menu bar keep working; **Show pill** brings it back. Quit from the menu stops the app until the
next login or the next `softvoice app`.

## What is on device, and what is not

- **Audio** is recorded, transcribed and synthesised on your Mac. It is never written to disk and never sent anywhere.
- **The agent's replies** are read from the hook payload on your Mac and spoken locally. Anything that looks like a key or token is replaced with the word "redacted" before it is spoken; code blocks, tables and URLs are skipped.
- **The network** is used once, to download the models from Hugging Face. After that you can work offline.
- **Nothing is collected**: no analytics, no accounts, no telemetry.

## Configuration

`~/.softvoice/config.toml` (`softvoice config` prints it) lists every setting with its default,
all commented out; remove the `# ` from a line to change it. Restart the daemon after changes
(`softvoice restart`) and relaunch the app (`softvoice autostart on` again, or Quit and `softvoice app`).

| key | default | meaning |
| --- | --- | --- |
| `voice` | `alba` | a predefined voice, or a path to a short WAV to clone |
| `language` | `english` | Pocket TTS model: `english`, `french`, `german`, `spanish`, `italian`, `portuguese`, `dutch`, or the tiny `english_18m_2026-10` |
| `max_chars` | `0` | cut long replies here; 0 speaks the whole reply |
| `speak_whole_turn` | `true` | speak every substantial text block of the turn, not only the last |
| `interim_min_chars` | `200` | shorter blocks before tool calls count as progress notes and are skipped |
| `speak_notifications` | `["permission_prompt"]` | add `"idle_prompt"` to be nagged |
| `interrupt_on_prompt` | `true` | stop speaking when you send a prompt |
| `announce_project` | `false` | prefix replies with the project folder name |
| `hotkey` | `alt_r` | the talk key: `alt_r`, `alt_l`, `cmd_r`, `ctrl_r`, `shift_r`, `fn`, `f1`…`f20`, or a combination such as `alt+space`, `ctrl+shift+d` (modifiers `alt`, `cmd`, `ctrl`, `shift`, `fn` plus a letter, digit, `space`, `tab` or F-key) |
| `stt_model` | `mlx-community/parakeet-tdt-0.6b-v3` | any Parakeet model in the mlx-community collection |
| `auto_submit` | `false` | press Enter after pasting; off means the transcript waits in your prompt for review |
| `send_words` | `["send it", ...]` | say one at the end of a take to send it hands-free |
| `tap_threshold_ms` | `350` | shorter press is tap-to-talk, longer is push-to-talk |
| `dictation_pause_ms` | `700` | pause that commits a sentence to the preview |
| `dictation_silence_s` | `8` | silence that finishes a dictation session |
| `panel` / `menu_bar_icon` | `true` | show the floating pill / the menu bar icon |
| `highlight_on_page` | `true` | underline the sentence being read in the front window |
| `clear_selection` | `true` | after you select text and press play, ask the app to drop the selection (native apps and editors; the Claude app ignores the request) |
| `accent` | `"#E8735A"` | the pill's live colour (waveform, speaker) |
| `underline` | `"#AAAAAA"` | the colour of the underline on the page |
| `hands_free` | `false` | hands-free by default |
| `end_silence_ms` | `900` | pause that ends your utterance |
| `listen_timeout_s` | `10` | close the mic when you say nothing |
| `earcon` | `true` | beeps when the mic opens and closes |
| `cancel_words` | `["cancel", ...]` | say one of these to discard a take |
| `paste_targets` | terminals, Claude, VS Code, Cursor, JetBrains, Codex | bundle ids hands-free may paste into (dictation you start yourself pastes anywhere) |

Set `SOFTVOICE_DISABLED=1` in an agent's environment to silence it without uninstalling.

## How it fits together

```
Claude Code / Codex ──Stop hook (stdin JSON)──▶ softvoice hook ──unix socket──▶ daemon
                                                 (40 ms, no ML imports)         │ clean markdown
                                                                                 │ Pocket TTS stream
                                                                                 ▼ speakers
you ──tap or hold the key──▶ softvoice app ──Parakeet──▶ paste into the focused prompt
                       ▲ hands-free: the daemon's "speech_end" event opens the mic,
                         Silero VAD ends the take, the transcript is pasted (+ Enter)
```

The hook command is tiny and imports no ML code, so it never slows the agent down. The daemon
holds the voice model warm between turns. The app holds the listener: the key watcher, the mic,
Parakeet, the pill and the underline.

## Status

Early, and in daily use by its author on an M4 MacBook Air. Verified live: the hands-free loop,
the pill, dictation sessions with Enter and Escape, the Option+Space talk key, follow-along text
and the underline on the page. Verified without a human: hook latency, speech from Stop and
Notification payloads, interruption on new prompts, the daemon's event stream, VAD end-of-utterance
timing on recorded speech, and a Pocket TTS to Parakeet round trip. Not yet: languages other than
English, a signed app bundle, Windows or Linux (the listener needs Apple's MLX).

Found a rough edge? Open an issue with the lines from `softvoice log` and `~/.softvoice/app.log`.

## Credits

[Pocket TTS](https://github.com/kyutai-labs/pocket-tts) by Kyutai. [Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
by NVIDIA (CC-BY-4.0), converted for MLX by the [mlx-community](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3)
and run with [parakeet-mlx](https://github.com/senstella/parakeet-mlx) by senstella. [Silero VAD](https://github.com/snakers4/silero-vad)
for end-of-utterance detection. [rumps](https://github.com/jaredks/rumps) for the menu bar. See
[LANDSCAPE.md](LANDSCAPE.md) for the survey of voice tools this started from.
