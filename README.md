# voicechat

On-device voice for coding agents. Claude Code and Codex read their replies aloud, and you
talk back with a push-to-talk key. Nothing leaves your Mac.

- **Speaking**: [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) (Kyutai, 100M params, CPU, streams audio ~200 ms after the text arrives)
- **Listening**: [Parakeet TDT 0.6B v3](https://github.com/senstella/parakeet-mlx) (NVIDIA, via MLX on Apple Silicon)
- **Integration**: the agents' own `Stop`, `Notification` and `UserPromptSubmit` hooks. No MCP server, no wrapping the terminal.

English first. Apple Silicon Mac, macOS 14 or newer.

## Install

```bash
brew install uv
git clone <this repo> voicechat && cd voicechat
uv sync
uv run voicechat install
```

`install` writes three hooks into `~/.claude/settings.json` (a backup is kept next to it) and,
if `~/.codex` exists, into `~/.codex/hooks.json`. Restart your Claude Code sessions so they pick
the hooks up. Codex needs a one-time `/hooks` to trust them.

First use downloads the Pocket TTS weights (~440 MB) and, for listening, Parakeet (~1.2 GB).

## Hearing replies

Nothing else to run. When an agent finishes a turn, its Stop hook calls `voicechat hook`, which
hands the reply to a small daemon (started on demand, kept warm) that cleans and speaks it:

- code blocks, tables, URLs and long paths are dropped or shortened: look at the screen for those
- markdown is flattened; bullets become sentences so the voice pauses
- anything that looks like a key or token is replaced with "redacted"
- long replies are cut at a sentence boundary after `max_chars` (default 700) with "More on screen."
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

## Hands-free

```bash
voicechat listen --hands-free
```

A conversation loop. Each time the daemon finishes speaking an agent's reply:

1. a short high beep: the mic is open
2. you talk; Silero VAD waits until you pause for `end_silence_ms` (0.9 s)
3. a short low beep: the mic is closed; Parakeet transcribes
4. the text is pasted into the agent's prompt and Enter is pressed

Say nothing for `listen_timeout_s` (10 s) and the mic closes. Say "cancel" or "never mind" to
discard a take. Hold the push-to-talk key at any moment to interrupt the speaker and take over.
If you typed a prompt yourself, or interrupted the speaker, the mic stays closed.

The transcript is only pasted when the frontmost app is a terminal or agent app (`paste_targets`,
a list of bundle-id patterns) or the app you last used push-to-talk in. Otherwise it goes to the
clipboard and `listen` tells you.

## Configuration

`~/.voicechat/config.toml` (`voicechat config` prints it). Restart the daemon after changes.

| key | default | meaning |
| --- | --- | --- |
| `voice` | `alba` | a predefined voice, or a path to a short WAV to clone |
| `language` | `english` | Pocket TTS model: `english`, `french`, `german`, `spanish`, `italian`, `portuguese`, `dutch`, or the tiny `english_18m_2026-10` |
| `max_chars` | `700` | where to cut long replies |
| `speak_notifications` | `["permission_prompt"]` | add `"idle_prompt"` to be nagged |
| `interrupt_on_prompt` | `true` | stop speaking when you send a prompt |
| `announce_project` | `false` | prefix replies with the project folder name |
| `hotkey` | `alt_r` | push-to-talk key (pynput name: `alt_r`, `cmd_r`, `ctrl_r`, `f5`, ...) |
| `stt_model` | `mlx-community/parakeet-tdt-0.6b-v3` | any Parakeet model in the mlx-community collection |
| `auto_submit` | `false` | press Enter after pasting (push-to-talk; hands-free always submits) |
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

Prototype. Verified without a human: hook latency, speech from Stop and Notification payloads,
interruption on new prompts, the daemon's event stream, VAD end-of-utterance timing on recorded
speech, and a Pocket TTS to Parakeet round trip. Needs a human at the mic: push-to-talk and the
hands-free loop. Not yet: languages other than English, a single-binary build.
See [LANDSCAPE.md](LANDSCAPE.md) for the survey this is based on.
