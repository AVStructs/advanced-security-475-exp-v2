"""Operator-side TCP listener for the control channel.

Binds a TCP port, accepts multiple target connections, maintains a session
registry, and exposes a line-oriented CLI for sending commands to chosen
sessions and reading replies.

Milestones covered here:
    M1: TCP listen + accept, PING/PONG round trip.
    M2: Per-session handler thread, session registry, graceful eviction on
        peer disconnect, reconnect-friendly (no residual state).
    M4: Command dispatch recognises the v1 verbs (PING, STATUS, PLAY, STOP)
        uniformly - the operator does not care which are stubs on the target.

Protocol (v1, text, newline-terminated UTF-8):
    target -> operator on connect:  HELLO client_id=<id> version=1
    operator -> target request:     <VERB> [args]
    target -> operator reply:       <REPLY-LINE>

Dependencies: Python 3.9+ standard library only.
"""

from __future__ import annotations

import argparse
import configparser
import ipaddress
import logging
import os
import queue
import shlex
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "operator.ini"
)
PROTOCOL_VERSION = 1


@dataclass
class SessionConfig:
    """Runtime configuration for the listener.

    Attributes:
        bind_host: Interface address to bind. ``0.0.0.0`` for all interfaces.
        bind_port: TCP port to listen on.
        allowed_subnets: Optional list of CIDR strings. Empty list allows all.
        command_timeout: Seconds to wait for a reply after sending a command.
    """

    bind_host: str
    bind_port: int
    allowed_subnets: list[str]
    command_timeout: float


@dataclass
class _Request:
    """Work item placed on a session's outbox by the CLI."""

    verb: str
    reply_queue: "queue.Queue[Optional[str]]"


@dataclass
class Session:
    """Registry entry and request pipe for a connected target.

    The handler thread owns the socket: it reads the HELLO line, then loops
    on the outbox queue, sending each request and reading one reply line.
    The CLI never touches the socket directly; it submits a ``_Request`` and
    waits on the associated reply queue. This keeps request/reply strictly
    serialized per session and avoids interleaved reads.
    """

    sid: int
    sock: socket.socket
    peer: tuple
    outbox: "queue.Queue[Optional[_Request]]" = field(default_factory=queue.Queue)
    client_id: str = ""
    version: str = ""
    connected_at: float = field(default_factory=time.time)
    alive: bool = True


class SessionRegistry:
    """Thread-safe registry of live target sessions."""

    def __init__(self) -> None:
        self._next_sid = 1
        self._sessions: dict[int, Session] = {}
        self._lock = threading.Lock()

    def add(self, sock: socket.socket, peer: tuple) -> Session:
        """Register a newly accepted connection and return its ``Session``."""
        with self._lock:
            sid = self._next_sid
            self._next_sid += 1
            session = Session(sid=sid, sock=sock, peer=peer)
            self._sessions[sid] = session
            return session

    def remove(self, sid: int) -> None:
        """Remove a session by id. Safe to call multiple times."""
        with self._lock:
            self._sessions.pop(sid, None)

    def get(self, sid: int) -> Optional[Session]:
        """Return the session with ``sid`` or ``None`` if absent."""
        with self._lock:
            return self._sessions.get(sid)

    def snapshot(self) -> list[Session]:
        """Return a point-in-time list of live sessions, ordered by sid."""
        with self._lock:
            return sorted(self._sessions.values(), key=lambda s: s.sid)


class LineReader:
    """Buffered newline-delimited reader over a blocking socket.

    ``readline`` returns one line without its terminator, or ``None`` on EOF.
    """

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


def parse_hello(line: str) -> dict[str, str]:
    """Parse a ``HELLO key=value ...`` greeting.

    Args:
        line: Raw line as received (without newline terminator).

    Returns:
        Mapping of keys to values. The verb itself is not included.

    Raises:
        ValueError: If the line does not begin with ``HELLO``.
    """
    parts = line.strip().split()
    if not parts or parts[0] != "HELLO":
        raise ValueError(f"expected HELLO, got {line!r}")
    attrs: dict[str, str] = {}
    for kv in parts[1:]:
        if "=" in kv:
            k, v = kv.split("=", 1)
            attrs[k] = v
    return attrs


def is_allowed(peer_ip: str, allowed_subnets: list[str]) -> bool:
    """Return True if ``peer_ip`` is in any of ``allowed_subnets``.

    An empty ``allowed_subnets`` list allows any peer. Invalid CIDR entries
    are skipped.
    """
    if not allowed_subnets:
        return True
    try:
        addr = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    for cidr in allowed_subnets:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def session_loop(
    session: Session,
    registry: SessionRegistry,
    cfg: SessionConfig,
    log: logging.Logger,
) -> None:
    """Own the socket for one session: HELLO, then dispatch outbox requests.

    Shutdown conditions:
        * Peer EOF or socket error at any point.
        * A ``None`` sentinel placed on the outbox (operator-initiated kick).
    """
    reader = LineReader(session.sock)
    try:
        hello = reader.readline(timeout=10.0)
        if hello is None:
            log.warning("sid=%d peer=%s disconnected before HELLO",
                        session.sid, session.peer)
            return
        try:
            attrs = parse_hello(hello)
        except ValueError as exc:
            log.warning("sid=%d bad hello: %s", session.sid, exc)
            return
        session.client_id = attrs.get("client_id", "")
        session.version = attrs.get("version", "")
        log.info(
            "sid=%d peer=%s client_id=%s version=%s connected",
            session.sid, session.peer,
            session.client_id or "?", session.version or "?",
        )

        while True:
            item = session.outbox.get()
            if item is None:
                return
            try:
                send_line(session.sock, item.verb)
                reply = reader.readline(timeout=cfg.command_timeout)
            except (OSError, socket.timeout) as exc:
                log.warning("sid=%d send/recv error: %s", session.sid, exc)
                item.reply_queue.put(None)
                return
            item.reply_queue.put(reply)
            if reply is None:
                log.info("sid=%d eof after request", session.sid)
                return
    finally:
        session.alive = False
        try:
            session.sock.close()
        except OSError:
            pass
        registry.remove(session.sid)
        log.info("sid=%d removed", session.sid)


def accept_loop(
    server: socket.socket,
    registry: SessionRegistry,
    cfg: SessionConfig,
    log: logging.Logger,
    stop_event: threading.Event,
) -> None:
    """Accept incoming connections until ``stop_event`` is set."""
    server.settimeout(1.0)
    while not stop_event.is_set():
        try:
            sock, peer = server.accept()
        except socket.timeout:
            continue
        except OSError as exc:
            if stop_event.is_set():
                return
            log.error("accept failed: %s", exc)
            continue

        peer_ip = peer[0]
        if not is_allowed(peer_ip, cfg.allowed_subnets):
            log.warning("rejecting peer=%s (not in allowed_subnets)", peer)
            try:
                sock.close()
            except OSError:
                pass
            continue

        session = registry.add(sock, peer)
        t = threading.Thread(
            target=session_loop,
            args=(session, registry, cfg, log),
            name=f"session-{session.sid}",
            daemon=True,
        )
        t.start()


def send_command(session: Session, verb: str, timeout: float) -> Optional[str]:
    """Submit a command to a session and wait for the reply line.

    Returns ``None`` on timeout, socket error, or EOF.
    """
    reply_q: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=1)
    session.outbox.put(_Request(verb=verb, reply_queue=reply_q))
    try:
        return reply_q.get(timeout=timeout + 2.0)
    except queue.Empty:
        return None


def _format_session_row(s: Session) -> str:
    age = int(time.time() - s.connected_at)
    return (f"  sid={s.sid:<3} peer={s.peer[0]}:{s.peer[1]:<5} "
            f"client_id={s.client_id or '?':<16} uptime={age}s")


def cli_loop(
    registry: SessionRegistry,
    cfg: SessionConfig,
    stop_event: threading.Event,
) -> None:
    """Interactive command loop. Runs on the main thread.

    Commands:
        list                     Show live sessions.
        use <sid>                Select a default session for subsequent commands.
        send <verb> [args...]    Send a raw verb to the selected session.
        ping | status            Shortcuts.
        play <path> | stop       Media stubs (sent verbatim to target).
        broadcast <verb> [args]  Send to every live session.
        kick <sid>               Close a session.
        help | quit
    """
    selected: Optional[int] = None
    print("operator CLI ready. type 'help' for commands, 'quit' to exit.")
    while not stop_event.is_set():
        try:
            raw = input(f"op[{selected if selected is not None else '-'}]> ")
        except (EOFError, KeyboardInterrupt):
            print()
            stop_event.set()
            return
        line = raw.strip()
        if not line:
            continue
        try:
            argv = shlex.split(line)
        except ValueError as exc:
            print(f"parse error: {exc}")
            continue
        cmd, rest = argv[0].lower(), argv[1:]

        if cmd in ("quit", "exit"):
            stop_event.set()
            return

        if cmd == "help":
            print(cli_loop.__doc__ or "")
            continue

        if cmd == "list":
            sessions = registry.snapshot()
            if not sessions:
                print("  (no sessions)")
            else:
                for s in sessions:
                    print(_format_session_row(s))
            continue

        if cmd == "use":
            if len(rest) != 1 or not rest[0].isdigit():
                print("usage: use <sid>")
                continue
            sid = int(rest[0])
            if registry.get(sid) is None:
                print(f"no such session: {sid}")
                continue
            selected = sid
            continue

        if cmd == "broadcast":
            if not rest:
                print("usage: broadcast <verb> [args...]")
                continue
            verb = " ".join(rest)
            for s in registry.snapshot():
                reply = send_command(s, verb, cfg.command_timeout)
                print(f"  sid={s.sid} -> {reply!r}")
            continue

        if cmd == "kick":
            if len(rest) != 1 or not rest[0].isdigit():
                print("usage: kick <sid>")
                continue
            sid = int(rest[0])
            s = registry.get(sid)
            if s is None:
                print(f"no such session: {sid}")
                continue
            s.outbox.put(None)
            print(f"kicked sid={sid}")
            if selected == sid:
                selected = None
            continue

        # All remaining commands target the selected session.
        if selected is None or registry.get(selected) is None:
            print("no session selected. use 'list' then 'use <sid>'.")
            selected = None
            continue
        s = registry.get(selected)
        if s is None:
            continue

        if cmd == "send":
            if not rest:
                print("usage: send <verb> [args...]")
                continue
            verb = " ".join(rest)
        elif cmd == "ping":
            verb = "PING"
        elif cmd == "status":
            verb = "STATUS"
        elif cmd == "play":
            if not rest:
                print("usage: play <path>")
                continue
            verb = "PLAY " + " ".join(rest)
        elif cmd == "stop":
            verb = "STOP"
        else:
            print(f"unknown command: {cmd}. type 'help'.")
            continue

        reply = send_command(s, verb, cfg.command_timeout)
        print(f"  <- {reply!r}")


def load_config(path: str) -> SessionConfig:
    """Load listener configuration from an INI file.

    The file must contain a ``[listener]`` section. Missing optional keys fall
    back to sensible defaults for an isolated lab LAN.
    """
    parser = configparser.ConfigParser()
    if not parser.read(path, encoding="utf-8"):
        raise FileNotFoundError(path)
    if "listener" not in parser:
        raise ValueError(f"{path}: missing [listener] section")
    sec = parser["listener"]
    raw_subnets = sec.get("allowed_subnets", "").strip()
    subnets = [s.strip() for s in raw_subnets.split(",") if s.strip()]
    return SessionConfig(
        bind_host=sec.get("bind_host", "0.0.0.0"),
        bind_port=sec.getint("bind_port", 47001),
        allowed_subnets=subnets,
        command_timeout=sec.getfloat("command_timeout_seconds", 10.0),
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Control-channel operator listener.")
    parser.add_argument(
        "-c", "--config", default=DEFAULT_CONFIG_PATH,
        help="path to operator.ini (default: alongside this script)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="enable DEBUG logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("operator")

    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        log.error("config error: %s", exc)
        return 2

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((cfg.bind_host, cfg.bind_port))
    except OSError as exc:
        log.error("bind %s:%d failed: %s", cfg.bind_host, cfg.bind_port, exc)
        return 2
    server.listen(16)
    log.info("listening on %s:%d (protocol v%d)",
             cfg.bind_host, cfg.bind_port, PROTOCOL_VERSION)

    registry = SessionRegistry()
    stop_event = threading.Event()

    accept_thread = threading.Thread(
        target=accept_loop,
        args=(server, registry, cfg, log, stop_event),
        name="accept",
        daemon=True,
    )
    accept_thread.start()

    try:
        cli_loop(registry, cfg, stop_event)
    finally:
        stop_event.set()
        try:
            server.close()
        except OSError:
            pass
        for s in registry.snapshot():
            s.outbox.put(None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
