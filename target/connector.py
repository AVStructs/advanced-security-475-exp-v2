"""Target-side connector for the control channel.

Opens an outbound TCP connection to the operator, sends the HELLO greeting,
and services one command-reply exchange at a time over a single long-lived
socket. Reconnects with exponential backoff if the socket drops.

PLAY starts ``cv2_hack.py`` (dev) or ``cv2_hack.exe`` beside this program (frozen)
in a child process.
STOP terminates that process. The connector itself uses only the standard
library; the media subprocess requires packages from ``requirements.txt``.

Protocol (v1, text, newline-terminated UTF-8):
    target -> operator on connect:  HELLO client_id=<id> version=1
    operator -> target request:     <VERB> [args]
    target -> operator reply:       <REPLY-LINE>
"""

from __future__ import annotations

import argparse
import configparser
import logging
import os
import platform
import random
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional


def _bundle_dir() -> str:
    """Directory used for ``target.ini`` and frozen media sibling exes.

    When running under PyInstaller (``sys.frozen``), this is the folder that
    contains the ``.exe``. Otherwise it is the directory of ``connector.py``.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


DEFAULT_CONFIG_PATH = os.path.join(_bundle_dir(), "target.ini")
PROTOCOL_VERSION = 1

_media_proc: Optional[subprocess.Popen] = None
# When True (default), media child uses CREATE_NO_WINDOW on Windows (no flash).
# Set False with --show-media-console to surface Python/OpenCV errors in a console.
_hide_media_console: bool = True


@dataclass
class ConnectorConfig:
    """Runtime configuration for the connector.

    Attributes:
        operator_host: Hostname or IP of the operator/listener.
        operator_port: TCP port of the operator/listener.
        client_name: Short identifier sent in HELLO for operator logs.
        reconnect_seconds: Initial backoff after a failed connect or drop.
        max_reconnect_seconds: Ceiling for exponential backoff.
        recv_timeout: Per-read socket timeout. Keep large to allow idle sockets
            to remain open between commands.
        media_root: Absolute directory containing ``cv2_hack.py`` and assets.
        default_video: Optional path relative to ``media_root`` for bare PLAY.
        default_audio: Optional path relative to ``media_root`` if no
            ``<stem>_audio.mp3`` exists beside the video file.
    """

    operator_host: str
    operator_port: int
    client_name: str
    reconnect_seconds: float
    max_reconnect_seconds: float
    recv_timeout: float
    media_root: str
    default_video: str
    default_audio: str


class LineReader:
    """Buffered newline-delimited reader over a blocking socket."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray()

    def readline(self, timeout: Optional[float]) -> Optional[str]:
        self._sock.settimeout(timeout)
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                if not self._buf:
                    return None
                line = self._buf.decode("utf-8", errors="replace")
                self._buf.clear()
                return line.rstrip("\r")
            self._buf.extend(chunk)
        idx = self._buf.index(b"\n")
        line = self._buf[:idx].decode("utf-8", errors="replace").rstrip("\r")
        del self._buf[: idx + 1]
        return line


def send_line(sock: socket.socket, line: str) -> None:
    """Send a single UTF-8 line terminated with ``\\n``."""
    sock.sendall((line + "\n").encode("utf-8"))


def _abs_under_root(path: str, root: str) -> str:
    """Resolve ``path`` to an absolute path, treating non-absolute as under ``root``."""
    path = path.strip()
    if not path:
        return ""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(root, path))


def _audio_for_video(video_abs: str, cfg: ConnectorConfig) -> Optional[str]:
    """Pick an audio file beside the video (``<stem>_audio.mp3``) or ``default_audio``."""
    vdir, vfile = os.path.split(video_abs)
    stem, _ = os.path.splitext(vfile)
    candidate = os.path.join(vdir, f"{stem}_audio.mp3")
    if os.path.isfile(candidate):
        return candidate
    if cfg.default_audio:
        fallback = _abs_under_root(cfg.default_audio, cfg.media_root)
        if os.path.isfile(fallback):
            return fallback
    return None


def _stop_media_proc(log: logging.Logger) -> None:
    """Terminate the media child process if it is still running."""
    global _media_proc
    if _media_proc is None:
        return
    if _media_proc.poll() is not None:
        _media_proc = None
        return
    _media_proc.terminate()
    try:
        _media_proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        log.warning("media process did not exit on terminate; killing")
        _media_proc.kill()
        try:
            _media_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log.warning("media process still alive after kill")
    _media_proc = None


def _handle_ping(_args: str, _log: logging.Logger, _cfg: ConnectorConfig) -> str:
    return "PONG"


def _handle_status(_args: str, _log: logging.Logger, _cfg: ConnectorConfig) -> str:
    global _media_proc
    if _media_proc is not None and _media_proc.poll() is None:
        return f"PLAYING pid={_media_proc.pid}"
    return "IDLE"


def _handle_play(args: str, log: logging.Logger, cfg: ConnectorConfig) -> str:
    """Start ``cv2_hack.py`` with resolved video and audio paths."""
    global _media_proc

    raw = args.strip()
    video_arg = raw if raw else cfg.default_video
    if not video_arg:
        return "ERR missing path"

    video_abs = _abs_under_root(video_arg, cfg.media_root)
    if not os.path.isfile(video_abs):
        return f"ERR video not found: {video_abs}"

    audio_abs = _audio_for_video(video_abs, cfg)
    if not audio_abs:
        return "ERR no audio file (expected <stem>_audio.mp3 beside video or default_audio in target.ini)"

    _stop_media_proc(log)

    if getattr(sys, "frozen", False):
        media_exe = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "cv2_hack.exe")
        if not os.path.isfile(media_exe):
            return f"ERR cv2_hack.exe not found beside connector: {media_exe}"
        argv = [media_exe, "--video", video_abs, "--audio", audio_abs]
    else:
        script = os.path.join(cfg.media_root, "cv2_hack.py")
        if not os.path.isfile(script):
            return f"ERR cv2_hack.py not found under media_root: {cfg.media_root}"
        argv = [sys.executable, script, "--video", video_abs, "--audio", audio_abs]

    popen_kw: dict = {
        "args": argv,
        "cwd": cfg.media_root,
    }
    if sys.platform == "win32" and _hide_media_console:
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        _media_proc = subprocess.Popen(**popen_kw)
    except OSError as exc:
        log.error("failed to spawn media process: %s", exc)
        return f"ERR spawn {exc!s}"

    time.sleep(0.4)
    if _media_proc.poll() is not None:
        rc = _media_proc.returncode
        log.error(
            "media process exited immediately rc=%s (run cv2_hack with same args "
            "in a console, or start connector with --show-media-console)",
            rc,
        )
        _media_proc = None
        return f"ERR media exited immediately rc={rc}"

    log.info("PLAY started pid=%s video=%s audio=%s", _media_proc.pid, video_abs, audio_abs)
    return f"OK play pid={_media_proc.pid} video={video_abs}"


def _handle_stop(_args: str, log: logging.Logger, _cfg: ConnectorConfig) -> str:
    global _media_proc
    if _media_proc is None or _media_proc.poll() is not None:
        _media_proc = None
        log.info("STOP (no active media)")
        return "OK stop idle"

    _stop_media_proc(log)
    log.info("STOP media process terminated")
    return "OK stop"


Handler = Callable[[str, logging.Logger, ConnectorConfig], str]

HANDLERS: dict[str, Handler] = {
    "PING": _handle_ping,
    "STATUS": _handle_status,
    "PLAY": _handle_play,
    "STOP": _handle_stop,
}


def dispatch(line: str, log: logging.Logger, cfg: ConnectorConfig) -> str:
    """Route a received request line to its handler and return the reply."""
    stripped = line.strip()
    if not stripped:
        return "ERR empty"
    if " " in stripped:
        verb, args = stripped.split(" ", 1)
    else:
        verb, args = stripped, ""
    handler = HANDLERS.get(verb.upper())
    if handler is None:
        return f"ERR unknown verb {verb!r}"
    try:
        return handler(args, log, cfg)
    except Exception as exc:  # handler bugs must not kill the session
        log.exception("handler %s raised", verb)
        return f"ERR handler {exc!s}"


def _hostname_suffix() -> str:
    """Best-effort short hostname for HELLO when ``client_name`` is unset."""
    try:
        name = platform.node() or socket.gethostname()
    except OSError:
        name = "unknown"
    return name.split(".")[0] or "unknown"


def run_once(cfg: ConnectorConfig, log: logging.Logger) -> None:
    """Connect, greet, and service commands until the peer closes.

    Raises:
        OSError: Propagated on connect or socket error so the outer loop can
            back off and retry.
    """
    client_id = cfg.client_name or _hostname_suffix()
    with socket.create_connection(
        (cfg.operator_host, cfg.operator_port), timeout=10.0
    ) as sock:
        try:
            sock.settimeout(None)
            log.info(
                "connected to %s:%d as client_id=%s",
                cfg.operator_host,
                cfg.operator_port,
                client_id,
            )
            send_line(sock, f"HELLO client_id={client_id} version={PROTOCOL_VERSION}")
            reader = LineReader(sock)
            while True:
                line = reader.readline(timeout=cfg.recv_timeout)
                if line is None:
                    log.info("operator closed connection")
                    return
                log.debug("req: %s", line)
                reply = dispatch(line, log, cfg)
                log.debug("rep: %s", reply)
                send_line(sock, reply)
        finally:
            # Avoid leaving fullscreen playback running without an operator session.
            _stop_media_proc(log)


def reconnect_loop(cfg: ConnectorConfig, log: logging.Logger) -> None:
    """Run ``run_once`` forever with bounded exponential backoff + jitter.

    Backoff resets to ``reconnect_seconds`` after a session that stayed up
    for at least ``reconnect_seconds * 2`` seconds, so transient network
    hiccups do not permanently inflate the delay.
    """
    delay = cfg.reconnect_seconds
    while True:
        started = time.monotonic()
        try:
            run_once(cfg, log)
        except (OSError, socket.timeout) as exc:
            log.warning("connection error: %s", exc)
        except Exception:
            log.exception("unexpected error in session")
        uptime = time.monotonic() - started
        if uptime >= cfg.reconnect_seconds * 2:
            delay = cfg.reconnect_seconds
        sleep_for = delay * (0.5 + random.random())
        log.info("reconnecting in %.1fs", sleep_for)
        time.sleep(sleep_for)
        delay = min(delay * 2.0, cfg.max_reconnect_seconds)


def load_config(path: str) -> ConnectorConfig:
    """Load connector configuration from an INI file.

    The file must contain a ``[connector]`` section. An optional ``[media]``
    section configures paths for ``cv2_hack.py`` playback.
    """
    parser = configparser.ConfigParser()
    if not parser.read(path, encoding="utf-8"):
        raise FileNotFoundError(path)
    if "connector" not in parser:
        raise ValueError(f"{path}: missing [connector] section")
    sec = parser["connector"]
    ini_dir = os.path.dirname(os.path.abspath(path))
    if parser.has_section("media"):
        m = parser["media"]
        pr_rel = (m.get("project_root") or "..").strip() or ".."
        media_root = os.path.normpath(os.path.join(ini_dir, pr_rel))
        default_video = (m.get("default_video") or "").strip()
        default_audio = (m.get("default_audio") or "").strip()
    else:
        media_root = os.path.normpath(os.path.join(ini_dir, ".."))
        default_video = ""
        default_audio = ""
    return ConnectorConfig(
        operator_host=sec.get("operator_host", "127.0.0.1"),
        operator_port=sec.getint("operator_port", 47001),
        client_name=sec.get("client_name", ""),
        reconnect_seconds=sec.getfloat("reconnect_seconds", 5.0),
        max_reconnect_seconds=sec.getfloat("max_reconnect_seconds", 60.0),
        recv_timeout=sec.getfloat("recv_timeout_seconds", 3600.0),
        media_root=media_root,
        default_video=default_video,
        default_audio=default_audio,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Control-channel target connector.")
    parser.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="path to target.ini (default: alongside this script)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable DEBUG logging",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run a single session then exit (no reconnect loop)",
    )
    parser.add_argument(
        "--show-media-console",
        action="store_true",
        help="on Windows, do not hide the media player console (debug import/GPU errors)",
    )
    args = parser.parse_args(argv)

    global _hide_media_console
    if args.show_media_console:
        _hide_media_console = False

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("connector")

    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        log.error("config error: %s", exc)
        return 2

    if args.once:
        try:
            run_once(cfg, log)
        except (OSError, socket.timeout) as exc:
            log.error("connection error: %s", exc)
            return 1
        return 0

    try:
        reconnect_loop(cfg, log)
    except KeyboardInterrupt:
        log.info("interrupted, exiting")
        _stop_media_proc(log)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
