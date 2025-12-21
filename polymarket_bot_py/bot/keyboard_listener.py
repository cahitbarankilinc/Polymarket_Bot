from __future__ import annotations

import logging
from threading import Event

from pynput import keyboard


class StopController:
    """Global stop flag driven by keyboard shortcuts (ESC / Ctrl+C)."""

    def __init__(self) -> None:
        self._stop_event = Event()
        self._listener: keyboard.Listener | None = None

    def start(self) -> None:
        if self._listener is None:
            self._listener = keyboard.Listener(on_press=self._on_press)
            self._listener.start()

    def request_stop(self, reason: str) -> None:
        if not self._stop_event.is_set():
            logging.warning(reason)
            self._stop_event.set()

    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == keyboard.Key.esc:
            self.request_stop("STOP requested by ESC")
