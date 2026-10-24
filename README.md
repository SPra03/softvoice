# voicechat

On-device voice for coding agents. Claude Code and Codex read their replies aloud, and you
talk back with a push-to-talk key. Nothing leaves your Mac.

- **Speaking**: [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) (Kyutai, 100M params, CPU, streams audio ~200 ms after the text arrives)
- **Listening**: [Parakeet TDT 0.6B v3](https://github.com/senstella/parakeet-mlx) (NVIDIA, via MLX on Apple Silicon)
- **Integration**: the agents' own `Stop`, `Notification` and `UserPromptSubmit` hooks. No MCP server, no wrapping the terminal.

English first. Apple Silicon Mac, macOS 14 or newer. MIT licence.

## Install

```bash
brew install uv
uv tool install voicechat
voicechat setup
voicechat install
```

Until the first PyPI release, install from GitHub instead:
`uv tool install git+https://github.com/SPra03/voicechat`. Upgrade later with
`uv tool upgrade voicechat`.

`setup` downloads the two models once (Pocket TTS, about 230 MB; Parakeet, 2.5 GB) and asks
macOS for the permissions below. `install` writes three hooks into `~/.claude/settings.json` (a
backup is kept next to it) and, if `~/.codex` exists, into `~/.codex/hooks.json`. Restart your
Claude Code sessions so they pick the hooks up. Codex needs a one-time `/hooks` to trust them.

Then `voicechat app --hands-free` starts the floating pill. Add it to your login items if you
want it always there.

### Permissions

macOS grants these to the app that owns the terminal you run voicechat from (Terminal, iTerm,
the Claude desktop app, VS Code), not to voicechat itself. Run it from the terminal you use for
Claude Code, and grant them again if you switch terminals.

| permission | for | asked |
| --- | --- | --- |
| Microphone | listening | the first time the mic opens |
| Accessibility | pasting your words into the prompt, reading the page for the underline | by `setup`, or the first paste |
| Input Monitoring | seeing the talk key and scroll events | by `setup`, or the first `listen` or `app` |

Nothing leaves the machine: no network after the models are downloaded, no analytics.

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

## Talking

```bash
voicechat listen
```

Hold **right Option**, speak, release. The transcript is pasted wherever your cursor is: the
Claude Code prompt in a terminal, the desktop app, anything. Pressing the key also interrupts
whatever is being spoken. `--auto-submit` presses Enter for you; `--no-paste` only prints.

macOS asks once for **Input Monitoring** (to see the key) and **Accessibility** (to paste) for the
terminal you run it in, plus **Microphone**. Run `voicechat listen` from the same terminal you use
for Claude Code.

## The app: a floating pill and a menu bar light

```bash
voicechat app --hands-free
```

A small dark glass pill (36 points tall) floats above every window, bottom right by default.
Drag it anywhere; it remembers the spot. Clicking it never steals focus, so your cursor stays in
the prompt. It uses one accent colour, and the accent always means "live": the waveform while
the mic listens, the speaker while the voice talks. Everything else is grey. Whenever text shows, the capsule becomes a rounded rectangle so words never run into
the curve, and the text is a single line that scrolls, newest words at the right.

| button | click | shows |
| --- | --- | --- |
| mic | start a dictation session | coral at rest (talk is the next thing to do), a live coral waveform while it listens, grey while the voice speaks or it transcribes |
| speaker | stop the voice while it speaks; when quiet, read the text you have selected in the front app, or replay the last reply if nothing is selected | coral stop while speaking, grey play otherwise, slashed when muted |

Exactly one thing on the pill is coral at any time, and it is the thing to tap next.

### Following along while it speaks

While a reply is read, the pill shows the sentence being spoken on one line: the word being
said is white, the words already said grey, the rest dim. Long sentences slide left so the
current word stays in view, with the clipped edge fading out. The daemon speaks one sentence at
a time and learns its own speaking rate, so the timing stays close.

On top of that, a thin light grey underline is drawn under that sentence in the front window
itself, line by line, found through macOS accessibility. It works where the app exposes
its text: the Claude desktop app (it switches its accessibility tree on when asked), Terminal,
VS Code and most native apps. The underline follows the page: every scroll event (seen by the
same event tap that watches the talk key) makes it re-read its position at once, and a slow
safety read twice a second covers keyboard scrolling and scrollbar drags. Text that has scrolled
out of view gets no underline until it comes back. Turn it off with the pill's menu or
`highlight_on_page = false`.

### Dictation session

Click the mic (or tap the key) and the pill grows to the left into **waveform · live text · ✕ · ✓**,
with the speaker staying exactly where it was. Committed sentences are white; the sentence still
forming, and the hint text, are grey; the line scrolls so the newest words are always visible.
Talk as long as you like. Each time you pause for `dictation_pause_ms` (0.7 s) the sentence is committed to the
preview; the sentence you are still saying is re-transcribed about once a second so you see it
forming. Then:

- **✓**, clicking the mic, or tapping the key pastes the whole text into your prompt at once
- **✕** or saying "cancel" discards it
- ending with "send it" pastes and presses Enter
- `dictation_silence_s` (8 s) of silence finishes it by itself

The paste goes to the app in front. If that is voicechat itself (opening the pill's menu
activates it, and macOS does not always hand activation back), it goes to the last other app that
was in front, after giving it focus again.

The preview lives in the pill rather than in the prompt on purpose: live text keeps revising
itself, and inside the pill we can rewrite it freely, while the prompt only gets one clean paste
that you can edit before sending.

**Press and hold** either button, or right-click, for the options: Hands-free, Auto-send,
Mute, Voice, config file, Quit. `panel = false` in the config turns the pill off.

The menu bar also gets a small status light (`menu_bar_icon = false` to hide it):

| icon | meaning |
| --- | --- |
| 🎙 | idle |
| 🎙 your turn | the agent finished; tap the key or click Talk |
| 🔊 | speaking (tap the key to interrupt) |
| 🔴 | mic open; 🔴 … means it hears you |
| ⏳ | transcribing |
| ✏️ | pasted into your prompt, waiting for your Enter |
| 🔇 | muted |

The menu has **Talk** (open the mic now; during a take it ends the take early),
**Stop speaking**, **Mute**, **Hands-free** and **Auto-send** checkboxes, the config file, and Quit.

The key: **tap** it (under `tap_threshold_ms`, 350 ms) to start a dictation session, tap again to
finish it. **Hold** it for push-to-talk. Press it while the agent speaks to interrupt. The
hands-free beep after a reply still uses the quick conversation take that ends on a pause.

## Hands-free

```bash
voicechat listen --hands-free
```

A conversation loop. Each time the daemon finishes speaking an agent's reply:

1. a short high beep: the mic is open
2. you talk; Silero VAD waits until you pause for `end_silence_ms` (0.9 s)
3. a short low beep: the mic is closed; Parakeet transcribes
4. the text is pasted into the agent's prompt, where you can read and edit it, then you press Enter

To send without touching the keyboard, end what you say with "send it" (`send_words`), or turn
on **Auto-send** in the menu bar (`auto_submit = true`), which presses Enter for you.

Say nothing for `listen_timeout_s` (10 s) and the mic closes. Say "cancel" or "never mind" to
discard a take. Hold the push-to-talk key at any moment to interrupt the speaker and take over.
If you typed a prompt yourself, or interrupted the speaker, the mic stays closed.

The transcript is only pasted when the frontmost app is a terminal or agent app (`paste_targets`,
a list of bundle-id patterns) or the app you last used push-to-talk in. Otherwise it goes to the
clipboard and `listen` tells you.

## Configuration

`~/.voicechat/config.toml` (`voicechat config` prints it) lists every setting with its default,
all commented out; remove the `# ` from a line to change it. Restart the daemon after changes
(`voicechat restart`) and relaunch the app if it is running.

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
| `hotkey` | `alt_r` | the key: `alt_r`, `alt_l`, `cmd_r`, `ctrl_r`, `shift_r`, `fn`, `f1`…`f20` |
| `stt_model` | `mlx-community/parakeet-tdt-0.6b-v3` | any Parakeet model in the mlx-community collection |
| `auto_submit` | `false` | press Enter after pasting; off means the transcript waits in your prompt for review |
| `send_words` | `["send it", ...]` | say one at the end of a take to send it hands-free |
| `tap_threshold_ms` | `350` | shorter press is tap-to-talk, longer is push-to-talk |
| `dictation_pause_ms` | `700` | pause that commits a sentence to the preview |
| `dictation_silence_s` | `8` | silence that finishes a dictation session |
| `panel` / `menu_bar_icon` | `true` | show the floating pill / the menu bar light |
| `highlight_on_page` | `true` | underline the sentence being read in the front window |
| `clear_selection` | `true` | after you select text and press play, ask the app to drop the selection (native apps and editors; the Claude app ignores the request) |
| `accent` | `"#E8735A"` | the pill's live colour (waveform, speaker) |
| `underline` | `"#AAAAAA"` | the colour of the underline on the page |
| `hands_free` | `false` | make `voicechat listen` hands-free by default |
| `end_silence_ms` | `900` | pause that ends your utterance |
| `listen_timeout_s` | `10` | close the mic when you say nothing |
| `earcon` | `true` | beeps when the mic opens and closes |
| `cancel_words` | `["cancel", ...]` | say one of these to discard a take |
| `paste_targets` | terminals, Claude, VS Code, Cursor, JetBrains, Codex | bundle ids hands-free may paste into |

Set `VOICECHAT_DISABLED=1` in an agent's environment to silence it without uninstalling.

## How it fits together

```
Claude Code / Codex ──Stop hook (stdin JSON)──▶ voicechat hook ──unix socket──▶ daemon
                                                 (40 ms, no ML imports)         │ clean markdown
                                                                                 │ Pocket TTS stream
                                                                                 ▼ speakers
you ──hold key──▶ voicechat listen ──Parakeet──▶ paste into focused prompt
                       ▲ hands-free: the daemon's "speech_end" event opens the mic,
                         Silero VAD ends the take, the transcript is pasted + Enter
```

`voicechat uninstall` removes the hooks. Everything voicechat owns lives in `~/.voicechat`.

## Status

Early, and in daily use by its author on an M4 MacBook Air. Verified live: the hands-free loop,
the pill's buttons, dictation sessions, follow-along text and the underline on the page. Verified
without a human: hook latency, speech from Stop and Notification payloads, interruption on new
prompts, the daemon's event stream, VAD end-of-utterance timing on recorded speech, and a Pocket
TTS to Parakeet round trip. Not yet: languages other than English, a signed app bundle, Windows
or Linux.
See [LANDSCAPE.md](LANDSCAPE.md) for the survey this is based on.
