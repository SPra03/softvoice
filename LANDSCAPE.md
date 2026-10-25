# Voice for coding agents: lay of the land (24 Oct 2026)

Goal: talk to Claude Code / Codex and hear their replies, fully on device, English first,
as simple to install and use as Whisper.

Machine: MacBook Air M4, 24 GB, macOS 26.6.2, Claude Code 2.1.268, Node 26, system Python 3.9 only
(no uv, ffmpeg, whisper, or Codex installed).

## Verdict

- Input (speech to text) is a solved problem today, several ways. Output (reading the agent's
  reply aloud) is the gap: Claude Code and Codex have no built-in TTS, and the open source tools
  that add it are either heavy (MCP server + two local model servers), fragile (wrapping the TUI),
  or tiny one-person hook scripts.
- Both agents now expose an official `Stop` hook that hands a script the final reply text
  (`last_assistant_message`) on stdin. That is the clean integration point; no PTY wrapping, no
  depending on the model remembering to call a "speak" tool.
- Recommendation: build a small two-way tool on that hook, reusing existing on-device engines
  (Parakeet for STT, Pocket TTS or Kokoro for TTS). Nothing from scratch on the model side.

## What the agents already do

| Agent | Voice input | Spoken output | Hook for output |
| --- | --- | --- | --- |
| Claude Code CLI / VS Code | `/voice` since Mar 2026. Hold Space or tap. Audio is sent to Anthropic servers, not local. Needs claude.ai login. Free, no token use. 20 languages. Not in desktop-app Code tab or SSH/cloud. | None. Feature request #45251 closed "not planned" May 2026. | `Stop` hook with `last_assistant_message`; `async: true` runs without blocking. Hooks fire in terminal, IDE, and Desktop app. Docs explicitly mention read-aloud hooks. |
| Codex CLI | Hold-Space dictation added 0.105 (Feb 2026), removed 0.118. Newer builds have `/voice` realtime via OpenAI Realtime API (cloud). Desktop app has ChatGPT Voice. | None local. | `hooks.json` / `config.toml` `Stop` event with `last_assistant_message` on stdin; hooks must be trusted via `/hooks`. Older `notify` setting fires `agent-turn-complete` with the same text. |
| Claude Desktop (Mac) | Quick entry dictation on Caps Lock (chat). Unclear if it reaches the Code tab. | None. | Same Claude Code hooks apply to Code tab sessions. |

## Existing open source projects

| Project | Approach | Engines (local) | Two-way? | Notes |
| --- | --- | --- | --- | --- |
| VoiceMode (mbailey) ~1.4k stars, MIT | MCP server; Claude calls a `converse` tool that speaks then listens. Also a Claude Code plugin. | whisper.cpp STT, Kokoro TTS (run as local servers) | Yes | Needs uv, ffmpeg, portaudio, two model servers. Speaking depends on the model calling the tool; needs a CLAUDE.md instruction to speak every reply. |
| TalkiTo (robdmac) ~54 stars, AGPL-3 | Wraps `claude` / `codex` in a PTY, captures output, speaks it. | faster-whisper / pywhispercpp STT; Kokoro, Piper, KittenTTS, NeuTTS, `say` TTS | Yes | Author says MCP was too slow, hence the wrapper. Wrapping a TUI is fragile. AGPL. |
| aloud (softcane) 9 stars, MIT | Claude Code + Codex hooks → Unix socket → daemon with Kokoro loaded. Per-session opt-in by typing `aloud on`. | Kokoro (PyTorch CPU) | Output only | Good text cleaning (markdown, code, URLs, secret redaction, 240-char summary). Python 3.11, pipx, Hammerspoon. Closest to the output half. |
| claude_voice (cris-m) 5 stars, MIT | Claude Code plugin, hooks | Kokoro / Chatterbox / mlx-audio | Output only | Speaks summaries, long-command alerts, idle alerts. |
| Handy (cjpais) ~34.5k stars, MIT | System-wide push-to-talk dictation app (Rust/Tauri). Pastes into focused app. | Whisper (GGML), Parakeet V3, Silero VAD | Input only | Works in any terminal or the desktop app. Option+Space default. |
| Hex (anomalyco/hex, Rust rewrite) MIT | Same idea, macOS 15+, Parakeet/Whisper, TypeScript SDK for local transcription. | Parakeet, Whisper | Input only | Original Swift Hex (kitlangton) archived. |
| yap (finnvoor) ~1.6k stars, CC0 | CLI on Apple SpeechAnalyzer (macOS 26). `yap dictate` from mic, `yap transcribe` files, MCP server. | Apple on-device Speech | Input only | `brew install yap`. Zero model downloads. |

## On-device engines for Apple Silicon (English)

### Speech to text

| Engine | Why | Speed / latency (reported) | Runtime | License |
| --- | --- | --- | --- | --- |
| NVIDIA Parakeet TDT v3 0.6B | Best speed/accuracy for English dictation; 25 EU languages | ~0.19 s per short utterance via FluidAudio Core ML on M4 Pro; ~0.5 s via parakeet-mlx; ~190x real time batch | FluidAudio (Swift/Core ML, ANE), parakeet-mlx (Python/MLX), mlx-audio, Handy | Apache 2.0 code, CC-BY-4.0 weights |
| Parakeet EOU 120M | Streaming with end-of-utterance detection, English only | 160 ms chunks | FluidAudio | Apache 2.0 |
| Kyutai STT 1B en/fr | True streaming, 0.5 s delay, semantic VAD built in | real time on Mac/iPhone per Kyutai | moshi-mlx (`uvx --with moshi-mlx`) | MIT code, CC-BY-4.0 weights |
| Whisper large-v3-turbo | Most accurate multilingual; the familiar one | ~1 s per utterance via mlx-whisper; slower than Parakeet | WhisperKit, whisper.cpp, mlx-whisper | MIT |
| Apple SpeechAnalyzer | Built into macOS 26, on device, streaming, no downloads | 2x+ faster than Whisper large in tests; WER ~2% clean | Swift Speech framework, yap CLI | Apple |
| Moonshine v2 | Tiny streaming English models | 40x real time but WER ~25% for Tiny | ONNX | MIT (some models non-commercial) |

### Text to speech

| Engine | Why | Speed / latency (reported) | Runtime | License |
| --- | --- | --- | --- | --- |
| Pocket TTS 100M (Kyutai) ~10k stars | CPU-first, streaming, ~200 ms to first audio, 6x real time on M4 Air CPU (2 cores). Voice cloning. New 18M/7M/2M English models Oct 2026. | ~80 ms to first audio via FluidAudio Core ML | `pip install pocket-tts`, mlx-pocket-tts (MLX, `--stream`, HTTP serve), FluidAudio | MIT |
| Kokoro 82M | Best small English quality, 48 voices | ~14x real time on M4 GPU via MLX; 36-54 ms per short clip via Core ML. Not streaming (whole clip at once). | mlx-audio, kokoro-mlx, kokoro (PyTorch), FluidAudio | Apache 2.0 |
| Piper | Fastest (~33x), lower quality | | ONNX | MIT |
| KittenTTS 15M | Smallest | | ONNX | Apache 2.0 |
| macOS `say` | Zero dependencies, fallback | instant | built in | Apple |

### One-stop runtimes

- FluidAudio (Swift, Apache 2.0, ~3.2k stars): Parakeet TDT/EOU, Silero VAD, Kokoro, Pocket TTS, all Core ML on ANE/GPU. macOS 14+. Single-binary path.
- mlx-audio (Python, MIT, ~8k stars): Whisper, Parakeet, Voxtral STT; Kokoro, Qwen3-TTS, many TTS; `--stream`; OpenAI-compatible `/v1/audio/speech` and `/v1/audio/transcriptions` server. Fast-iteration path.

## Proposed build: `softvoice`

Phase 1, output (the missing piece):
- Daemon keeps the TTS model loaded. Claude Code `Stop` hook and Codex `Stop` hook post
  `last_assistant_message` to it over a Unix socket (`async: true` so the agent never waits).
- Cleaner: strip code blocks, paths, URLs, markdown, tables; speak a short summary by default
  with an option to speak everything; redact secret-looking strings.
- Streaming Pocket TTS so audio starts in under ~300 ms; sentence-chunked Kokoro as the alternative voice.
- Also speak `Notification` hooks (`permission_prompt`, `idle_prompt`) so you hear when it needs you.
- Works in terminal, VS Code, and the desktop app Code tab, for Claude Code and Codex.

Phase 2, input:
- Global push-to-talk hotkey → Parakeet (or Apple SpeechAnalyzer) → paste into the focused prompt.
- Hands-free mode: after TTS finishes, open the mic, use end-of-utterance detection, auto-submit.

Phase 3: other languages (Parakeet v3 covers 25 EU languages; Pocket TTS has 7; swap Whisper in for more).

Stack choice: Python + MLX (uv, mlx-audio / parakeet-mlx / mlx-pocket-tts) for the prototype,
install as `uv tool install`. Port to a single Swift binary on FluidAudio once the UX is settled.

## Sources

- https://code.claude.com/docs/en/voice-dictation
- https://code.claude.com/docs/en/hooks
- https://github.com/anthropics/claude-code/issues/45251
- https://learn.chatgpt.com/docs/hooks
- https://codex.danielvaughan.com/2026/03/28/codex-cli-voice-input-dictation
- https://smartscope.blog/en/blog/codex-cli-voice-input-wsl-removed-2026/
- https://agentsroom.dev/fr/blog/voice-mode-in-codex-opencode-antigravity-and-claude-code
- https://support.claude.com/en/articles/12626668-use-quick-entry-with-claude-desktop-on-mac
- https://github.com/mbailey/voicemode
- https://github.com/rwunsch/voicemode-local
- https://github.com/robdmac/talkito
- https://news.ycombinator.com/item?id=45927954
- https://github.com/softcane/aloud
- https://github.com/cris-m/claude_voice
- https://github.com/cjpais/Handy
- https://github.com/anomalyco/hex
- https://github.com/finnvoor/yap
- https://github.com/FluidInference/FluidAudio
- https://docs.fluidinference.com/
- https://github.com/senstella/parakeet-mlx
- https://github.com/Blaizzy/mlx-audio
- https://github.com/kyutai-labs/pocket-tts
- https://huggingface.co/vanch007/mlx-pocket-tts
- https://github.com/kyutai-labs/delayed-streams-modeling
- https://localaimaster.com/blog/best-speech-to-text-mac
- https://trywalkie.com/en/blog/on-device-speech-to-text-benchmark
- https://www.yaps.ai/blog/best-local-tts-models
- https://localaimaster.com/blog/best-local-tts-models
- https://9to5mac.com/2025/06/18/apple-devices-offer-amazing-speech-to-text-transcription-in-developer-betas-shows-test
- https://dev.to/iravoice/apple-speechanalyzer-vs-whispercpp-a-40-speaker-mac-benchmark-40i4
- https://dev.classmethod.jp/en/articles/claude-code-kokoro-tts-local-voice-response/
