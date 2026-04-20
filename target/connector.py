"""Target-side connector for the control channel.

Opens an outbound TCP connection to the operator, sends the HELLO greeting,
and services one command-reply exchange at a time over a single long-lived
socket. Reconnects with exponential backoff if the socket drops.

Milestones covered here:
    M1: Outbound connect, HELLO, PING/PONG.
    M2: Reconnect with bounded exponential backoff.
    M4: Stubs for PLAY <path>, STOP, STATUS. ``command PLAY <path>`` simply
        logs and returns OK so the operator end-to-end path can be validated
        before the media subsystem is wired up.

Protocol (v1, text, newline-terminated UTF-8):
    target -> operator on connect:  HELLO client_id=<id> version=1
    operator -> target request:     <VERB> [args]
    target -> operator reply:       <REPLY-LINE>

Dependencies: Python 3.9+ standard library only. No pip packages required.
"""

from __future__ import annotations

import argparse
import configparser
import logging
import os
import platform
import random
import socket
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional


DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "target.ini"
)
PROTOCOL_VERSION = 1


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
    """

    operator_host: str
    operator_port: int
    client_name: str
    reconnect_seconds: float
    max_reconnect_seconds: float
    recv_timeout: float


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


# ---------------------------------------------------------------------------
# Command handlers.
#
# Each handler returns the reply line to send back. They are intentionally
# stubs for v1 - the media teammate can replace the PLAY/STOP bodies with
# real IPC later without touching the socket layer.
# ---------------------------------------------------------------------------


def _handle_ping(_args: str, _log: logging.Logger) -> str:
    return "PONG"


def _handle_status(_args: str, _log: logging.Logger) -> str:
    return "IDLE"


def _handle_play(args: str, log: logging.Logger) -> str:
    path = args.strip()
    if not path:
        return "ERR missing path"
    log.info("PLAY stub: path=%r", path)
    return f"OK play path={path}"


def _handle_stop(_args: str, log: logging.Logger) -> str:
    log.info("STOP stub")
    return "OK stop"


HANDLERS: dict[str, Callable[[str, logging.Logger], str]] = {
    "PING": _handle_ping,
    "STATUS": _handle_status,
    "PLAY": _handle_play,
    "STOP": _handle_stop,
}


def dispatch(line: str, log: logging.Logger) -> str:
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
        return handler(args, log)
    except Exception as exc:  # handler bugs must not kill the session
        log.exception("handler %s raised", verb)
        return f"ERR handler {exc!s}"


# ---------------------------------------------------------------------------
# Connection lifecycle.
# ---------------------------------------------------------------------------


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
        sock.settimeout(None)
        log.info("connected to %s:%d as client_id=%s",
                 cfg.operator_host, cfg.operator_port, client_id)
        send_line(sock, f"HELLO client_id={client_id} version={PROTOCOL_VERSION}")
        reader = LineReader(sock)
        while True:
            line = reader.readline(timeout=cfg.recv_timeout)
            if line is None:
                log.info("operator closed connection")
                return
            log.debug("req: %s", line)
            reply = dispatch(line, log)
            log.debug("rep: %s", reply)
            send_line(sock, reply)


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
        # Random jitter in [0.5x, 1.5x] smooths reconnect storms.
        sleep_for = delay * (0.5 + random.random())
        log.info("reconnecting in %.1fs", sleep_for)
        time.sleep(sleep_for)
        delay = min(delay * 2.0, cfg.max_reconnect_seconds)


def load_config(path: str) -> ConnectorConfig:
    """Load connector configuration from an INI file.

    The file must contain a ``[connector]`` section.
    """
    parser = configparser.ConfigParser()
    if not parser.read(path, encoding="utf-8"):
        raise FileNotFoundError(path)
    if "connector" not in parser:
        raise ValueError(f"{path}: missing [connector] section")
    sec = parser["connector"]
    return ConnectorConfig(
        operator_host=sec.get("operator_host", "127.0.0.1"),
        operator_port=sec.getint("operator_port", 47001),
        client_name=sec.get("client_name", ""),
        reconnect_seconds=sec.getfloat("reconnect_seconds", 5.0),
        max_reconnect_seconds=sec.getfloat("max_reconnect_seconds", 60.0),
        recv_timeout=sec.getfloat("recv_timeout_seconds", 3600.0),
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Control-channel target connector.")
    parser.add_argument(
        "-c", "--config", default=DEFAULT_CONFIG_PATH,
        help="path to target.ini (default: alongside this script)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="enable DEBUG logging",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="run a single session then exit (no reconnect loop)",
    )
    args = parser.parse_args(argv)

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
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
