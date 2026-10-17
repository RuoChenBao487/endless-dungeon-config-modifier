"""Create isolated sessions and launch the modified game process."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from .config import ModifierConfig, write_config


TOOL_ROOT = Path(__file__).resolve().parents[1]
GAME_ROOT = TOOL_ROOT.parent / "16.0"
SESSION_ROOT = TOOL_ROOT / "runtime" / "sessions"
LAST_LOG = TOOL_ROOT / "runtime" / "last_game.log"
SAVE_FILES = ("save_data.json", "run_save.json")


def read_game_version(game_dir: str | Path = GAME_ROOT) -> str:
    settings_path = Path(game_dir) / "dungeon" / "settings.py"
    try:
        source = settings_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    return match.group(1) if match else ""


def _session_name() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _safe_session_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(SESSION_ROOT.resolve())
        return True
    except ValueError:
        return False


def cleanup_session(session_dir: str | Path) -> bool:
    target = Path(session_dir)
    if not _safe_session_path(target) or not target.exists():
        return False
    shutil.rmtree(target)
    return True


def _windowless_python() -> Path:
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        candidate = executable.with_name("python.exe")
        if candidate.exists():
            return candidate
    return executable


@dataclass
class ManagedGame:
    process: subprocess.Popen
    session_dir: Path
    config_path: Path
    log_path: Path
    preserve_session: bool
    _log_handle: object

    def poll(self) -> int | None:
        code = self.process.poll()
        if code is not None:
            self.close()
        return code

    def close(self) -> None:
        handle = self._log_handle
        if handle is not None and not handle.closed:
            handle.close()
        self._log_handle = None

    def finish(self) -> None:
        self.close()
        try:
            LAST_LOG.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.is_file():
                shutil.copy2(self.log_path, LAST_LOG)
                self.log_path = LAST_LOG
        except OSError:
            pass
        if not self.preserve_session:
            cleanup_session(self.session_dir)

    def tail_log(self, limit: int = 4000) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-limit:]


def start_game(
    game_dir: str | Path,
    config: ModifierConfig,
    *,
    inherit_saves: bool = True,
    preserve_session: bool = False,
) -> ManagedGame:
    game_path = Path(game_dir).resolve()
    if not (game_path / "main.py").is_file():
        raise FileNotFoundError("所选目录中没有 main.py")
    version = read_game_version(game_path)
    if version != "16.0":
        raise ValueError(f"当前修改器适配 16.0，检测到版本：{version or '未知'}")

    session_dir = SESSION_ROOT / _session_name()
    session_dir.mkdir(parents=True, exist_ok=False)
    config_path = session_dir / "modifier_session.json"
    log_path = session_dir / "game.log"
    write_config(config_path, config)

    copied_saves: list[str] = []
    if inherit_saves:
        for name in SAVE_FILES:
            source = game_path / name
            if source.is_file():
                shutil.copy2(source, session_dir / name)
                copied_saves.append(name)

    metadata = {
        "game_dir": str(game_path),
        "game_version": version,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "inherit_saves": inherit_saves,
        "copied_saves": copied_saves,
        "preserve_session": preserve_session,
        "modifiers": config.validated().as_dict(),
    }
    (session_dir / "session_info.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        str(TOOL_ROOT)
        if not existing_path
        else str(TOOL_ROOT) + os.pathsep + existing_path
    )
    environment["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    environment["PYTHONUTF8"] = "1"

    command = [
        str(_windowless_python()),
        "-B",
        "-m",
        "modifier.runtime",
        "--game-dir",
        str(game_path),
        "--config",
        str(config_path),
        "--session-dir",
        str(session_dir),
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log_handle = log_path.open("w", encoding="utf-8", buffering=1)
    try:
        process = subprocess.Popen(
            command,
            cwd=game_path,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    except Exception:
        log_handle.close()
        cleanup_session(session_dir)
        raise
    return ManagedGame(
        process=process,
        session_dir=session_dir,
        config_path=config_path,
        log_path=log_path,
        preserve_session=preserve_session,
        _log_handle=log_handle,
    )
