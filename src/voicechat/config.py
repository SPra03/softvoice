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
    max_chars: int = 700  # cut cleaned replies here, at a sentence boundary
    truncation_suffix: str = "More on screen."
    speak_notifications: list[str] = field(default_factory=lambda: ["permission_prompt"])
    interrupt_on_prompt: bool = True  # stop speaking when you send a new prompt
    announce_project: bool = False  # prefix replies with the project folder name
    # Listening (push-to-talk)
    hotkey: str = "alt_r"  # pynput key name; hold to record, release to transcribe
    stt_model: str = "mlx-community/parakeet-tdt-0.6b-v3"
    auto_submit: bool = False  # press Enter after pasting the transcript
    paste_delay_ms: int = 60
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
