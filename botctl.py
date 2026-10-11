"""
Helpers for managing the Discord bot from the web UI.

- read/write the .env file
- build the invite link
- start/stop `bot.py` as a separate process (tracked with a PID file, so it
  survives Streamlit reruns and page refreshes)

No Streamlit imports here, so this module can be tested on its own.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import psutil

BASE = Path(__file__).resolve().parent
ENV_PATH = BASE / ".env"
PID_PATH = BASE / ".rodeo_bot.pid"
LOG_PATH = BASE / "bot.log"
BOT_SCRIPT = BASE / "bot.py"

# Discord permission bits (https://discord.com/developers/docs/topics/permissions)
PERMISSIONS = {
    "View Channels": 1 << 10,
    "Send Messages": 1 << 11,
    "Embed Links": 1 << 14,
    "Attach Files": 1 << 15,
    "Read Message History": 1 << 16,
    "Use Application Commands": 1 << 31,
}
DEFAULT_PERMISSIONS = ["Send Messages", "Embed Links", "Attach Files"]  # = 51200

_proc: subprocess.Popen | None = None


# ---------------------------------------------------------------- .env
def load_env(path: Path | None = None) -> dict[str, str]:
    path = path or ENV_PATH
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        if s.startswith("export "):
            s = s[7:]
        key, value = s.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def _format_value(value: str) -> str:
    return f'"{value}"' if re.search(r"[\s#]", value) else value


def save_env(updates: dict[str, str | None], path: Path | None = None) -> None:
    """Set keys in .env, keeping other lines and comments. A value of None removes the key."""
    path = path or ENV_PATH
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(updates)
    result: list[str] = []
    for line in lines:
        s = line.strip()
        body = s[7:] if s.startswith("export ") else s
        key = body.split("=", 1)[0].strip() if "=" in body and not s.startswith("#") else None
        if key in pending:
            value = pending.pop(key)
            if value is not None:
                result.append(f"{key}={_format_value(value)}")
        else:
            result.append(line)
    for key, value in pending.items():
        if value is not None:
            result.append(f"{key}={_format_value(value)}")
    path.write_text("\n".join(result) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- invite link
def permissions_int(names) -> int:
    return sum(PERMISSIONS[n] for n in names if n in PERMISSIONS)


def names_from_int(value: int) -> list[str]:
    return [n for n, bit in PERMISSIONS.items() if value & bit]


def valid_app_id(app_id: str) -> bool:
    return bool(re.fullmatch(r"\d{15,25}", app_id.strip()))


def invite_url(app_id: str, permissions: int) -> str:
    return (
        "https://discord.com/oauth2/authorize"
        f"?client_id={app_id.strip()}&permissions={permissions}"
        "&integration_type=0&scope=bot+applications.commands"
    )


# ---------------------------------------------------------------- process control
def _read_pid() -> int | None:
    try:
        return int(PID_PATH.read_text().strip())
    except (OSError, ValueError):
        return None


def _is_our_bot(proc: psutil.Process) -> bool:
    try:
        return BOT_SCRIPT.name in " ".join(proc.cmdline())
    except psutil.Error:
        return False


def status() -> dict:
    """{'running': bool, 'pid': int | None}"""
    if _proc is not None:
        _proc.poll()  # reap it if it has exited, so it doesn't linger as a zombie
    pid = _read_pid()
    if pid and psutil.pid_exists(pid):
        try:
            p = psutil.Process(pid)
            if p.status() != psutil.STATUS_ZOMBIE and _is_our_bot(p):
                return {"running": True, "pid": pid}
        except psutil.Error:
            pass
    PID_PATH.unlink(missing_ok=True)
    return {"running": False, "pid": None}


def start(extra_env: dict[str, str] | None = None) -> tuple[bool, str]:
    """Start bot.py. Returns (ok, code); code is one of
    started / already_running / no_token / no_bot_file."""
    global _proc
    if status()["running"]:
        return False, "already_running"
    if not BOT_SCRIPT.exists():
        return False, "no_bot_file"
    # .env wins over variables already set in the shell, since the UI edits .env
    env = {**os.environ, **load_env(), **(extra_env or {})}
    if not env.get("DISCORD_TOKEN"):
        return False, "no_token"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    kwargs: dict = {}
    if os.name == "nt":
        # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        kwargs["creationflags"] = 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True

    with open(LOG_PATH, "a", encoding="utf-8") as log:
        log.write(f"\n--- starting bot {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log.flush()
        _proc = subprocess.Popen(
            [sys.executable, str(BOT_SCRIPT)],
            cwd=str(BASE),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
    PID_PATH.write_text(str(_proc.pid))
    return True, "started"


def stop() -> tuple[bool, str]:
    """Stop the bot. Returns (ok, code); code is stopped / not_running."""
    st = status()
    if not st["running"]:
        return False, "not_running"
    try:
        parent = psutil.Process(st["pid"])
        procs = [parent] + parent.children(recursive=True)
        for p in procs:
            try:
                p.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(procs, timeout=5)
        for p in alive:
            try:
                p.kill()
            except psutil.Error:
                pass
    except psutil.Error:
        pass
    if _proc is not None:
        _proc.poll()
    PID_PATH.unlink(missing_ok=True)
    return True, "stopped"


def tail_log(lines: int = 40, max_bytes: int = 32_000) -> str:
    try:
        with open(LOG_PATH, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
    except OSError:
        return ""
    return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-lines:])
