"""Fault injection for Experiment E1. Off by default, switched at runtime, fully undoable."""
import threading

from .schemas import FaultConfig


class FaultState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.config = FaultConfig()
        self._menu_calls = 0
        self._hold_calls = 0

    def set(self, config: FaultConfig) -> None:
        with self._lock:
            self.config = config
            self._menu_calls = 0
            self._hold_calls = 0

    def clear(self) -> None:
        self.set(FaultConfig())

    def menu_delay_seconds(self) -> float:
        """Seconds to sleep for this menu request (0 for most requests)."""
        with self._lock:
            if self.config.menu_delay_ms == 0:
                return 0.0
            self._menu_calls += 1
            if self._menu_calls % self.config.menu_delay_every_nth == 0:
                return self.config.menu_delay_ms / 1000
            return 0.0

    def should_fail_hold(self) -> bool:
        with self._lock:
            if self.config.hold_fail_every_nth == 0:
                return False
            self._hold_calls += 1
            return self._hold_calls % self.config.hold_fail_every_nth == 0


faults = FaultState()
