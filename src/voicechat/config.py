"""User configuration and well-known paths.

Everything voicechat owns lives under ~/.voicechat: the config file, the daemon's
Unix socket, its log, and its pid file.
"""

from __future__ import annotations

import dataclasses
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HOME_DIR = Path(os.environ.get("VOICECHAT_HOME", Path.home() / ".voicechat"))
CONFIG_PATH = HOME_DIR / "config.toml"
SOCKET_PATH = HOME_DIR / "daemon.sock"
LOG_PATH = HOME_DIR / "daemon.log"
PID_PATH = HOME_DIR / "daemon.pid"


@dataclass
class Config:
    # Speaking
    voice: str = "alba"  # a Pocket TTS predefined voice, or a path/URL to a WAV to clone
    language: str = "english"  # Pocket TTS model id, see `voicechat voices`
    max_chars: int = 1400  # cut cleaned replies here, at a sentence boundary
    speak_whole_turn: bool = True  # speak every substantial text block of the turn, not only the last one
    interim_min_chars: int = 200  # shorter blocks before tool calls are progress notes: skipped
    truncation_suffix: str = "More on screen."
    speak_notifications: list[str] = field(default_factory=lambda: ["permission_prompt"])
    interrupt_on_prompt: bool = True  # stop speaking when you send a new prompt
    announce_project: bool = False  # prefix replies with the project folder name
    # Listening (push-to-talk)
    hotkey: str = "alt_r"  # pynput key name; hold to record, release to transcribe
    stt_model: str = "mlx-community/parakeet-tdt-0.6b-v3"
    auto_submit: bool = False  # press Enter after pasting; off = the transcript waits in your prompt for review
    send_words: list[str] = field(default_factory=lambda: ["send it", "send", "go ahead and send"])  # say one at the end to send hands-free
    paste_delay_ms: int = 60
    tap_threshold_ms: int = 350  # shorter press = tap-to-talk (voice detection ends the take); longer = push-to-talk
    # The app's controls
    panel: bool = True  # floating two-button pill (talk, play/stop); drag it anywhere
    menu_bar_icon: bool = True  # status light in the menu bar
    highlight_on_page: bool = True  # while speaking, underline the sentence in the front window (best effort)
    clear_selection: bool = True  # after reading selected text, drop the selection so the underline shows
    accent: str = "#E8735A"  # the pill's one colour: the waveform while listening, the speaker while talking (hex)
    underline: str = "#AAAAAA"  # the underline under the sentence being read, on the page (hex)
    # Dictation session (mic click or key tap): stays open, previews live, pastes on confirm
    dictation_pause_ms: int = 700  # pause that closes one sentence and commits it to the preview
    dictation_silence_s: float = 8.0  # say nothing this long and the session finishes by itself
    dictation_preview_s: float = 1.0  # how often the unfinished sentence is re-transcribed for the preview
    dictation_max_s: float = 300.0
    # Hands-free: after a reply is spoken, open the mic, wait for you to finish, paste and send
    hands_free: bool = False
    end_silence_ms: int = 900  # how long a pause ends your utterance
    listen_timeout_s: float = 10.0  # close the mic if you say nothing
    max_utterance_s: float = 60.0
    earcon: bool = True  # short beep when the mic opens and when it closes
    cancel_words: list[str] = field(default_factory=lambda: ["cancel", "never mind", "nevermind", "scratch that"])
    # Hands-free pastes only into these apps (bundle ids, fnmatch patterns) or the app you last used push-to-talk in
    paste_targets: list[str] = field(default_factory=lambda: [
        "com.apple.Terminal", "com.googlecode.iterm2", "dev.warp.Warp-Stable", "com.mitchellh.ghostty",
        "net.kovidgoyal.kitty", "org.alacritty", "com.github.wez.wezterm", "co.zeit.hyper",
        "com.anthropic.claudefordesktop", "com.microsoft.VSCode", "com.microsoft.VSCodeInsiders",
        "com.todesktop.230313mzl4w4u92", "com.exafunction.windsurf", "com.jetbrains.*", "com.openai.*",
    ])

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        cfg = cls()
        if not path.exists():
            return cfg
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        names = {f.name for f in dataclasses.fields(cls)}
        for key, value in data.items():
            if key in names:
                setattr(cfg, key, value)
        return cfg

    def to_toml(self) -> str:
        lines = ["# voicechat configuration. Restart the daemon after editing: voicechat restart", ""]
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            lines.append(f"{f.name} = {_toml_value(value)}")
        return "\n".join(lines) + "\n"


def accent_rgb(value: str, fallback=(0.91, 0.45, 0.35)) -> tuple[float, float, float]:
    """'#E8735A' -> (r, g, b) in 0..1; anything unparsable gives the default coral."""
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    except Exception:
        return fallback


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def ensure_home() -> Path:
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    return HOME_DIR


def write_default_config(overwrite: bool = False) -> Path:
    ensure_home()
    if overwrite or not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(Config().to_toml())
    return CONFIG_PATH
