"""Command-line entry point. Heavy imports stay inside the commands that need them."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from voicechat import __version__
from voicechat.config import CONFIG_PATH, LOG_PATH, Config, write_default_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voicechat", description="On-device voice in and out for Claude Code and Codex.")
    parser.add_argument("--version", action="version", version=f"voicechat {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="run the speaker daemon (normally started for you)")
    p.add_argument("--foreground", "-f", action="store_true", help="log to the terminal as well")

    p = sub.add_parser("say", help="speak text through the daemon")
    p.add_argument("text", nargs="*", help="text to speak; reads stdin when omitted")
    p.add_argument("--raw", action="store_true", help="skip markdown cleaning")
    p.add_argument("--out", metavar="WAV", help="write a WAV file instead of speaking (loads the model in-process)")

    sub.add_parser("stop", help="stop speaking and clear the queue")
    sub.add_parser("mute", help="stay silent until unmuted")
    sub.add_parser("unmute", help="speak again")
    sub.add_parser("status", help="show daemon state")
    sub.add_parser("restart", help="stop the daemon; the next hook starts a fresh one")
    sub.add_parser("quit", help="stop the daemon")
    p = sub.add_parser("voice", help="switch the voice for this daemon run")
    p.add_argument("name", help="a predefined voice name or a WAV path to clone")
    sub.add_parser("voices", help="list predefined voices")
    p = sub.add_parser("log", help="show the daemon log")
    p.add_argument("-n", type=int, default=40)

    sub.add_parser("hook", help="agent hook entry: reads the hook JSON on stdin")
    p = sub.add_parser("notify", help="Codex legacy notify entry: JSON as an argument")
    p.add_argument("payload")

    sub.add_parser("setup", help="download the models and ask macOS for the permissions, so the first run is instant")
    p = sub.add_parser("install", help="write hooks into Claude Code and Codex settings")
    p.add_argument("--claude-only", action="store_true")
    p.add_argument("--codex-only", action="store_true")
    sub.add_parser("uninstall", help="remove voicechat hooks")
    sub.add_parser("config", help="print the config file path and contents")

    p = sub.add_parser("listen", help="push-to-talk: hold the hotkey, speak, release to paste")
    p.add_argument("--hotkey", help="pynput key name, e.g. alt_r, cmd_r, f5")
    p.add_argument("--auto-submit", action="store_true", help="press Enter after pasting")
    p.add_argument("--no-paste", action="store_true", help="print transcripts instead of pasting")
    p.add_argument("--hands-free", action="store_true", help="after each spoken reply, open the mic and send what you say")
    p = sub.add_parser("app", help="menu bar app: a mic icon that shows whose turn it is, with Talk, Stop, Mute, Hands-free")
    p.add_argument("--hotkey", help="pynput key name, e.g. alt_r, cmd_r, f5")
    p.add_argument("--auto-submit", action="store_true", help="press Enter after push-to-talk pastes")
    p.add_argument("--no-paste", action="store_true", help="print transcripts instead of pasting")
    hf = p.add_mutually_exclusive_group()
    hf.add_argument("--hands-free", dest="hands_free", action="store_true", default=None)
    hf.add_argument("--no-hands-free", dest="hands_free", action="store_false")
    p = sub.add_parser("autostart", help="run the app as a login item: starts at login, no terminal, back after a crash")
    p.add_argument("action", nargs="?", choices=["on", "off", "status"], default="status")
    p.add_argument("--hands-free", action="store_true", help="start hands-free (or set hands_free = true in the config)")
    p = sub.add_parser("transcribe", help="transcribe an audio file with Parakeet")
    p.add_argument("file")

    args = parser.parse_args(argv)
    return COMMANDS[args.cmd](args)


# -- speaking -----------------------------------------------------------------------

def cmd_serve(args) -> int:
    from voicechat.daemon import serve

    return serve(foreground=args.foreground)


def cmd_say(args) -> int:
    text = " ".join(args.text) if args.text else sys.stdin.read()
    if not text.strip():
        print("nothing to say", file=sys.stderr)
        return 1
    if args.out:
        import soundfile as sf

        from voicechat.clean import clean
        from voicechat.tts import Speaker

        cfg = Config.load()
        spoken = text if args.raw else clean(text, cfg.max_chars, cfg.truncation_suffix).text
        speaker = Speaker(cfg)
        t0 = time.monotonic()
        audio = speaker.synthesize(spoken)
        sf.write(args.out, audio, speaker.sample_rate)
        print(f"wrote {args.out}: {len(audio) / speaker.sample_rate:.1f}s audio in {time.monotonic() - t0:.1f}s")
        return 0
    return _send({"cmd": "speak", "text": text, "raw": args.raw, "meta": {"event": "say"}})


def cmd_simple(cmd: str, **fields):
    def run(args) -> int:
        return _send({"cmd": cmd, **fields}, autostart=cmd not in ("stop", "quit", "mute", "unmute"))

    return run


def cmd_status(args) -> int:
    from voicechat.client import alive, send

    if not alive():
        print("daemon: not running")
        return 1
    print(json.dumps(send({"cmd": "status"}, autostart=False), indent=2))
    return 0


def cmd_restart(args) -> int:
    from voicechat.client import alive, send

    from voicechat.config import PID_PATH

    old_pid = None
    try:
        old_pid = int(PID_PATH.read_text().strip() or 0) or None
    except (OSError, ValueError):
        pass
    if alive():
        send({"cmd": "quit"}, autostart=False)
    for _ in range(100):  # wait for the old process itself, not just its socket
        if not alive() and not (old_pid and _pid_running(old_pid)):
            break
        time.sleep(0.1)
    from voicechat.client import ensure_daemon

    ok = ensure_daemon()
    print("daemon restarted" if ok else "daemon did not come up; see: voicechat log")
    return 0 if ok else 1


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cmd_voice(args) -> int:
    return _send({"cmd": "voice", "voice": args.name})


def cmd_voices(args) -> int:
    from voicechat.tts import PREDEFINED_VOICES

    print("\n".join(PREDEFINED_VOICES))
    print("\nOr pass a path to a short WAV of a voice to clone. Set `voice` in", CONFIG_PATH)
    return 0


def cmd_log(args) -> int:
    if not LOG_PATH.exists():
        print("no log yet")
        return 0
    lines = LOG_PATH.read_text(errors="replace").splitlines()
    print("\n".join(lines[-args.n:]))
    return 0


def _send(req: dict, autostart: bool = True) -> int:
    from voicechat.client import DaemonUnavailable, send

    try:
        resp = send(req, autostart=autostart)
    except DaemonUnavailable as exc:
        print(exc, file=sys.stderr)
        return 1
    if not resp.get("ok"):
        print(resp.get("error", "failed"), file=sys.stderr)
        return 1
    extras = {k: v for k, v in resp.items() if k != "ok"}
    if extras:
        print(json.dumps(extras))
    return 0


# -- hooks --------------------------------------------------------------------------

def _hook_payload(raw: str) -> int:
    """Shared by `hook` (stdin) and `notify` (argv). Never fails loudly: agents must not notice us."""
    if os.environ.get("VOICECHAT_DISABLED"):
        return 0
    try:
        payload = json.loads(raw) if raw.strip() else {}
        cfg = Config.load()
        from voicechat.client import send
        from voicechat.hooks import interpret

        action = interpret(payload, cfg.speak_notifications, cfg.interrupt_on_prompt,
                           whole_turn=cfg.speak_whole_turn, interim_min_chars=cfg.interim_min_chars)
        if action.kind == "speak":
            send({"cmd": "speak", "text": action.text, "meta": action.meta})
        elif action.kind == "stop":
            send({"cmd": "stop", "reason": "prompt"}, autostart=False)
    except Exception as exc:  # log and stay silent: stdout must stay clean for Codex
        try:
            from voicechat.config import HOME_DIR, ensure_home

            ensure_home()
            with open(HOME_DIR / "hook.log", "a") as fh:
                fh.write(f"{time.strftime('%F %T')} {type(exc).__name__}: {exc}\n")
        except OSError:
            pass
    return 0


def cmd_hook(args) -> int:
    return _hook_payload(sys.stdin.read())


def cmd_notify(args) -> int:
    return _hook_payload(args.payload)


def cmd_setup(args) -> int:
    """Everything that would otherwise happen, slowly, the first time you use it."""
    from huggingface_hub import hf_hub_download

    from voicechat import permissions

    cfg = Config.load()
    print(f"config: {write_default_config()}")

    t0 = time.monotonic()
    print(f"Pocket TTS ({cfg.language}, voice {cfg.voice}): about 230 MB the first time", flush=True)
    from voicechat.tts import Speaker

    Speaker(cfg)
    print(f"  ready in {time.monotonic() - t0:.0f}s")

    t0 = time.monotonic()
    print(f"Parakeet ({cfg.stt_model}): 2.5 GB the first time", flush=True)
    for name in ("config.json", "model.safetensors"):  # the same two files parakeet-mlx loads
        hf_hub_download(cfg.stt_model, name)
    print(f"  ready in {time.monotonic() - t0:.0f}s")

    print("Permissions (granted to the app this terminal belongs to):")
    try:
        import sounddevice as sd

        with sd.InputStream(channels=1, samplerate=16000):  # makes macOS ask for the microphone now
            time.sleep(0.3)
        print("Microphone: opened")
    except Exception as exc:
        print(f"Microphone: could not open ({exc})")
    permissions.check_and_request(need_paste=True, need_hotkey=True)
    print("Next: `voicechat install` adds the hooks, then `voicechat app --hands-free` starts the pill.")
    return 0


def cmd_install(args) -> int:
    from voicechat import install as inst

    write_default_config()
    command = inst.hook_command()
    print(f"hook command: {command}")
    if not args.codex_only:
        path, backup = inst.install_claude(command)
        print(f"Claude Code: hooks written to {path}" + (f" (backup {backup.name})" if backup else ""))
        print("  Restart Claude Code sessions to pick them up.")
    if not args.claude_only:
        result = inst.install_codex(command)
        if result:
            path, backup = result
            print(f"Codex: hooks written to {path}" + (f" (backup {backup.name})" if backup else ""))
            print("  Run /hooks inside Codex once to trust them.")
        else:
            print("Codex: ~/.codex not found, skipped. When you install Codex, run `voicechat install --codex-only`.")
    print(f"config: {CONFIG_PATH}")
    return 0


def cmd_uninstall(args) -> int:
    from voicechat import install as inst

    for label, fn in (("Claude Code", inst.uninstall_claude), ("Codex", inst.uninstall_codex)):
        path = fn()
        print(f"{label}: {'removed from ' + str(path) if path else 'nothing to remove'}")
    return 0


def cmd_config(args) -> int:
    path = write_default_config()
    print(path)
    print(path.read_text())
    return 0


# -- listening ----------------------------------------------------------------------

def cmd_listen(args) -> int:
    from voicechat.ptt import listen

    cfg = Config.load()
    return listen(cfg, hotkey=args.hotkey or cfg.hotkey, auto_submit=args.auto_submit or cfg.auto_submit,
                  paste=not args.no_paste, hands_free=args.hands_free or cfg.hands_free)


def cmd_app(args) -> int:
    from voicechat.menubar import run_app

    cfg = Config.load()
    hands_free = cfg.hands_free if args.hands_free is None else args.hands_free
    return run_app(cfg, hotkey=args.hotkey or cfg.hotkey, auto_submit=args.auto_submit or cfg.auto_submit,
                   paste=not args.no_paste, hands_free=hands_free)


def cmd_autostart(args) -> int:
    from voicechat import autostart, instance

    if args.action == "on":
        other = instance.running_pid()
        if other:
            print(f"stopping the running copy (pid {other}) so the login item starts it fresh ...", flush=True)
            if not instance.quit(other):
                print("it did not stop; quit it yourself and run this again")
                return 1
        path = autostart.enable(["--hands-free"] if args.hands_free else [])
        time.sleep(1.5)
        st = autostart.status()
        print(f"login item: {path}")
        running = f" and is running now (pid {st['pid']})" if st.get("pid") else ""
        print(f"voicechat app starts at every login{running}. Output: {autostart.APP_LOG}")
        print("If macOS asks for the microphone, Accessibility or Input Monitoring again, that is because the app")
        print("now runs under Python instead of your terminal. Grant them once and they stick.")
        return 0
    if args.action == "off":
        if autostart.disable():
            print("login item removed and the app stopped. `voicechat app` starts it by hand.")
        else:
            print("no login item was installed.")
        return 0
    st = autostart.status()
    if not st["installed"]:
        print("not installed. `voicechat autostart on` makes the app start at login.")
    else:
        where = f"running (pid {st['pid']})" if st.get("pid") else ("loaded, not running" if st["loaded"] else "installed, not loaded")
        print(f"login item {autostart.PLIST_PATH}: {where}")
    return 0


def cmd_transcribe(args) -> int:
    from voicechat.stt import Transcriber

    cfg = Config.load()
    t = Transcriber(cfg.stt_model)
    t0 = time.monotonic()
    text = t.transcribe_file(Path(args.file))
    print(text)
    print(f"[{time.monotonic() - t0:.2f}s]", file=sys.stderr)
    return 0


COMMANDS = {
    "serve": cmd_serve,
    "say": cmd_say,
    "stop": cmd_simple("stop", reason="cli"),
    "mute": cmd_simple("mute"),
    "unmute": cmd_simple("unmute"),
    "status": cmd_status,
    "restart": cmd_restart,
    "quit": cmd_simple("quit"),
    "voice": cmd_voice,
    "voices": cmd_voices,
    "log": cmd_log,
    "hook": cmd_hook,
    "notify": cmd_notify,
    "setup": cmd_setup,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "config": cmd_config,
    "listen": cmd_listen,
    "app": cmd_app,
    "autostart": cmd_autostart,
    "transcribe": cmd_transcribe,
}
