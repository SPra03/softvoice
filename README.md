# voicechat

**Talk to Claude Code and Codex, and hear them talk back. Everything stays on your Mac.**

![macOS Apple Silicon](https://img.shields.io/badge/macOS%2014%2B-Apple%20Silicon-black?logo=apple)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
[![PyPI](https://img.shields.io/pypi/v/voicechat-mac?color=blue)](https://pypi.org/project/voicechat-mac/)
![On-device](https://img.shields.io/badge/your%20voice%20%26%20text-never%20leave%20your%20Mac-blue)
[![CI](https://github.com/SPra03/voicechat/actions/workflows/ci.yml/badge.svg)](https://github.com/SPra03/voicechat/actions/workflows/ci.yml)

Your coding agent finishes a turn and reads its reply aloud, underlining each sentence on the
page as it goes. You answer by talking: tap a key, say what you want, press Enter. A small glass
pill floats above your windows and shows what is happening. No accounts, no API keys, no audio
sent anywhere: after a one-time model download it works with the network unplugged.

- **Speaking**: [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) by Kyutai, a 100M-parameter voice that runs on the CPU and starts talking about 200 ms after the text arrives
- **Listening**: [Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) by NVIDIA, run through [parakeet-mlx](https://github.com/senstella/parakeet-mlx) on Apple Silicon; transcribes faster than you speak
- **Integration**: the agents' own `Stop`, `Notification` and `UserPromptSubmit` hooks. No MCP server, no wrapping the terminal, no changes to how you work

English first (the listener understands 24 other European languages; the voice has English, French, German, Spanish, Italian, Portuguese and Dutch). Apple Silicon Mac, macOS 14 or newer. MIT licence. Early, and in daily use by its author.

## Install

Three commands, with [uv](https://docs.astral.sh/uv/) doing the Python work:

```bash
brew install uv
uv tool install voicechat-mac
voicechat setup
```

(Or the newest commit straight from GitHub: `uv tool install git+https://github.com/SPra03/voicechat`.)

`setup` downloads the two models once (Pocket TTS, about 230 MB; Parakeet, 2.5 GB) and asks
macOS for the permissions below. Then:

```bash
voicechat install          # hooks into Claude Code (and Codex, if ~/.codex exists)
voicechat autostart on     # the pill, now and at every login, with no terminal left open
```

`install` writes three hooks into `~/.claude/settings.json` (a backup is kept next to it) and,
if `~/.codex` exists, into `~/.codex/hooks.json`. Restart your Claude Code sessions so they pick
the hooks up; Codex needs a one-time `/hooks` to trust them. Upgrade later with
`uv tool upgrade voicechat-mac`; `voicechat uninstall` removes the hooks, `voicechat autostart off`
the login item, and everything voicechat owns lives in `~/.voicechat`.

Needs about 4 GB of disk for the models and the Python environment, and about 2 GB of memory
while running. The models load once at start; idle, it uses no CPU.

### Permissions

macOS grants these to the app that owns the terminal you run voicechat from (Terminal, iTerm,
the Claude desktop app, VS Code), or to Python itself when the login item starts it. Each is
asked for once.

| permission | needed for | asked |
| --- | --- | --- |
| Microphone | listening | the first time the mic opens |
| Accessibility | pasting your words into the prompt; reading the page for the underline | by `setup`, or the first paste |
| Input Monitoring | seeing the talk key and scroll events | by `setup`, or the first `listen` or `app` |

If you grant Accessibility after the app has started, it restarts itself (under the login item)
so the underline can read the page.

## Everyday use

The talk key is **right Option** by default: the ⌥ key to the right of the space bar, chosen
because nothing else uses it on its own. Prefer a combination? One line in the config:
`hotkey = "alt+space"` (or `ctrl+shift+d`, `fn+space`, ...). A combination is swallowed, so the
app in front never sees it.

| when | you | voicechat |
| --- | --- | --- |
| any time | **tap** the talk key, or click the mic | opens a dictation session: talk as long as you like, your words appear in the pill |
| dictating | tap again, press **Enter**, or click **✓** | pastes everything into your prompt, where you can still edit it |
| dictating | press **Escape**, click **✕**, or say "cancel" | discards it |
| dictating | end with "send it" | pastes and presses Enter for you |
| any time | **hold** the talk key, speak, release | push-to-talk: a quick take, pasted where your cursor is |
| while it speaks | tap the talk key, or click the speaker | stops the voice |
| while it is quiet | click the speaker | reads the text you have selected in any app, or replays the last reply |
| hands-free on | just talk after the beep | after every spoken reply the mic opens by itself, pauses send |

Enter and Escape are only taken while a dictation session is open, and only on their own: Cmd,
Ctrl and Option combinations still reach your app. The second Enter, after the paste, sends your
prompt as usual.

### What is on device, and what is not

- **Audio** is recorded, transcribed and synthesised on your Mac. It is never written to disk and never sent anywhere.
- **The agent's replies** are read from the hook payload on your Mac and spoken locally. Anything that looks like a key or token is replaced with the word "redacted" before it is spoken; code blocks, tables and URLs are skipped.
- **The network** is used once, to download the models from Hugging Face. After that you can work offline.
- **Nothing is collected**: no analytics, no accounts, no telemetry.

## Hearing replies

Nothing else to run. When an agent finishes a turn, its Stop hook calls `voicechat hook`, which
hands the reply to a small daemon (started on demand, kept warm) that cleans and speaks it:

- the whole turn is spoken, not just the last paragraph: every text block of at least
  `interim_min_chars` (200) since your message, so a long answer written before a tool call is not
  lost, while short progress notes between tool calls are skipped
- code blocks, tables, URLs and long paths are dropped or shortened: look at the screen for those
- markdown is flattened; bullets become sentences so the voice pauses
- anything that looks like a key or token is replaced with "redacted"
- the whole reply is spoken, however long; set `max_chars` to cut long replies at a sentence boundary with "More on screen."
- permission prompts are spoken too; sending a new prompt interrupts speech

```bash
voicechat say "hello there"      # speak anything
voicechat stop                   # shut up
voicechat mute / unmute          # stay silent across turns
voicechat voice jane             # try another voice (see `voicechat voices`)
voicechat status | log | restart
```

### Following along

While a reply is read, the pill shows the sentence being spoken on one line: the words already
said and the current one are white, the rest grey, and long sentences slide left so the current
word stays in view. The daemon speaks one sentence at a time and learns its own speaking rate, so
the timing stays close.

On the page itself, a thin light grey underline is drawn under that sentence in the front window,
line by line, found through macOS accessibility. It works where the app exposes its text: the
Claude desktop app, Terminal, VS Code and most native apps. The underline follows the page: every
scroll event makes it re-read its position at once, and a slow safety read twice a second covers
keyboard scrolling and scrollbar drags. When there is nothing to underline, the app log says why.
Turn it off with the pill's menu or `highlight_on_page = false`.

## Talking

The transcript is pasted wherever your cursor is: the Claude Code prompt in a terminal, the
desktop app, anything. Dictation and push-to-talk paste into whatever app is in front, since you
started them on purpose. Hands-free, where the mic opens by itself, is more careful: it pastes
only into terminals and agent apps (`paste_targets`) or an app you have dictated into before, and
otherwise puts the text on the clipboard and tells you.

Without the pill, from a terminal: `voicechat listen` (hold the key, speak, release) and
`voicechat listen --hands-free`. `--auto-submit` presses Enter for you; `--no-paste` only prints.

## The pill and the menu bar

```bash
voicechat app --hands-free    # by hand; `voicechat autostart on` does this at every login
```

A small dark glass pill (36 points tall) floats above every window, bottom right by default.
Drag it anywhere; it remembers the spot. Clicking it never steals focus, so your cursor stays in
the prompt. It uses one accent colour, and the accent always means "live": the waveform while the
mic listens, the speaker while the voice talks. Everything else is grey. Whenever text shows, the
capsule becomes a rounded rectangle, and the text is a single line that scrolls, newest words at
the right.

| button | click | shows |
| --- | --- | --- |
| mic | start a dictation session | coral at rest (talk is the next thing to do), a live coral waveform while it listens, grey while the voice speaks or it transcribes |
| speaker | stop the voice while it speaks; when quiet, read the text you have selected in the front app, or replay the last reply if nothing is selected | coral stop while speaking, grey play otherwise, slashed when muted |

Exactly one thing on the pill is coral at any time, and it is the thing to tap next.

**Dictation session**: click the mic (or tap the key) and the pill grows to the left into
**waveform · live text · ✕ · ✓**. Committed sentences are white; the sentence still forming, and
the hint text, are grey; the line scrolls so the newest words are always visible. Each time you
pause for `dictation_pause_ms` (0.7 s) the sentence is committed; the one you are still saying is
re-transcribed about once a second so you see it forming. `dictation_silence_s` (8 s) of silence
finishes the session by itself. The preview lives in the pill rather than in the prompt on
purpose: live text keeps revising itself, and the prompt only gets one clean paste that you can
edit before sending.

**Press and hold** either button, or right-click, for the options: Hands-free, Auto-send, Mute,
Underline, Voice, Hide pill, config file, Quit. `panel = false` in the config turns the pill off.

The menu bar gets one small waveform, the same in every state (the pill is where state shows);
`menu_bar_icon = false` hides it. Its first line says what voicechat is doing right now, and the
menu has **Hide pill** / **Show pill**, **Talk**, **Stop speaking**, **Mute**, **Hands-free** and
**Auto-send**, the config file, and Quit.

### Running without a terminal

`voicechat autostart on` registers the app as a macOS login item: it starts when you log in, needs
no terminal, and comes back by itself if it ever crashes (not after you quit it on purpose).
`voicechat autostart off` removes the login item and stops the app; `voicechat autostart` shows
the state. The app's output goes to `~/.voicechat/app.log`.

Only one copy of the app runs at a time: `voicechat app` while it is already running just shows
the pill of the running one. **Hide pill** tucks the pill away while the key, the voice and the
menu bar keep working; **Show pill** brings it back. Quit from the menu stops the app until the
next login or the next `voicechat app`.

## Hands-free

A conversation loop, on with `--hands-free`, the menu, or `hands_free = true`. Each time the
daemon finishes speaking a reply:

1. a short high beep: the mic is open
2. you talk; Silero VAD waits until you pause for `end_silence_ms` (0.9 s)
3. a short low beep: the mic is closed; Parakeet transcribes
4. the text is pasted into the agent's prompt, where you can read and edit it, then you press Enter

To send without touching the keyboard, end what you say with "send it" (`send_words`), or turn
on **Auto-send** (`auto_submit = true`), which presses Enter for you. Say nothing for
`listen_timeout_s` (10 s) and the mic closes. Say "cancel" or "never mind" to discard a take.
Hold the talk key at any moment to interrupt the speaker and take over. If you typed a prompt
yourself, or interrupted the speaker, the mic stays closed.

## Configuration

`~/.voicechat/config.toml` (`voicechat config` prints it) lists every setting with its default,
all commented out; remove the `# ` from a line to change it. Restart the daemon after changes
(`voicechat restart`) and relaunch the app (`voicechat autostart on` again, or Quit and `voicechat app`).

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

Set `VOICECHAT_DISABLED=1` in an agent's environment to silence it without uninstalling.

## How it fits together

```
Claude Code / Codex ──Stop hook (stdin JSON)──▶ voicechat hook ──unix socket──▶ daemon
                                                 (40 ms, no ML imports)         │ clean markdown
                                                                                 │ Pocket TTS stream
                                                                                 ▼ speakers
you ──tap or hold the key──▶ voicechat app ──Parakeet──▶ paste into the focused prompt
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

Found a rough edge? Open an issue with the lines from `voicechat log` and `~/.voicechat/app.log`.

## Credits

[Pocket TTS](https://github.com/kyutai-labs/pocket-tts) by Kyutai. [Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
by NVIDIA (CC-BY-4.0), converted for MLX by the [mlx-community](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3)
and run with [parakeet-mlx](https://github.com/senstella/parakeet-mlx) by senstella. [Silero VAD](https://github.com/snakers4/silero-vad)
for end-of-utterance detection. [rumps](https://github.com/jaredks/rumps) for the menu bar. See
[LANDSCAPE.md](LANDSCAPE.md) for the survey of voice tools this started from.
