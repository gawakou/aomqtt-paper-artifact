from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .config import AOMQTTConfig


@dataclass(frozen=True)
class RotationState:
    """Computed token rotation state for a point in time."""

    current_epoch: str
    previous_epoch: Optional[str]
    in_overlap: bool
    seconds_into_epoch: float
    seconds_to_next_epoch: float


class TokenRotation:
    """Time-window based token rotation helper.

    Epoch is calculated as floor(timestamp / rotation_interval_sec). The epoch
    string is fed into TopicTokenizer so the same plaintext topic maps to a
    different token topic across time windows.

    In the first rotation_overlap_sec seconds after a new epoch begins,
    publisher can send to both current and previous epoch tokens. Subscriber can
    subscribe to both current and previous token filters. This overlap reduces
    delivery loss when clocks or subscription updates are not perfectly aligned.
    """

    def __init__(self, config: AOMQTTConfig):
        config.validate()
        self.config = config

    @property
    def enabled(self) -> bool:
        return bool(self.config.rotation_enabled)

    def epoch_index(self, timestamp: Optional[float] = None) -> int:
        if timestamp is None:
            timestamp = time.time()
        return int(timestamp // self.config.rotation_interval_sec)

    def epoch(self, timestamp: Optional[float] = None) -> Optional[str]:
        if not self.enabled:
            return None
        return str(self.epoch_index(timestamp))

    def state(self, timestamp: Optional[float] = None) -> RotationState:
        if timestamp is None:
            timestamp = time.time()
        idx = self.epoch_index(timestamp)
        start = idx * self.config.rotation_interval_sec
        seconds_into = timestamp - start
        seconds_to_next = self.config.rotation_interval_sec - seconds_into
        in_overlap = self.enabled and seconds_into < self.config.rotation_overlap_sec
        previous = str(idx - 1) if self.enabled and idx > 0 and in_overlap else None
        return RotationState(
            current_epoch=str(idx),
            previous_epoch=previous,
            in_overlap=in_overlap,
            seconds_into_epoch=seconds_into,
            seconds_to_next_epoch=seconds_to_next,
        )

    def publish_epochs(self, timestamp: Optional[float] = None) -> list[Optional[str]]:
        """Epochs a publisher should use for one logical message."""
        if not self.enabled:
            return [None]
        s = self.state(timestamp)
        epochs: list[Optional[str]] = [s.current_epoch]
        if s.previous_epoch is not None:
            epochs.append(s.previous_epoch)
        return epochs

    def subscribe_epochs(self, timestamp: Optional[float] = None) -> list[Optional[str]]:
        """Epochs a subscriber should subscribe to at this point in time."""
        return self.publish_epochs(timestamp)
