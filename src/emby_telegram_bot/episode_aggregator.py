from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any


class EpisodeAggregator:
    def __init__(
        self,
        flush_delay_seconds: int,
        flush_callback: Callable[[dict[str, Any], list[str]], None],
    ) -> None:
        self._flush_delay_seconds = flush_delay_seconds
        self._flush_callback = flush_callback
        self._buffer: dict[tuple[str, int], list[int]] = defaultdict(list)
        self._timers: dict[tuple[str, int], threading.Timer] = {}
        self._samples: dict[tuple[str, int], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def add_episode(self, item: dict[str, Any]) -> None:
        series_name = item.get("SeriesName") or "Serie"
        season_number = int(item.get("ParentIndexNumber") or 0)
        episode_number = int(item.get("IndexNumber") or 0)
        key = (series_name, season_number)

        with self._lock:
            self._buffer[key].append(episode_number)
            self._samples[key] = item
            if key not in self._timers:
                timer = threading.Timer(self._flush_delay_seconds, self._flush, args=(key,))
                timer.daemon = True
                self._timers[key] = timer
                timer.start()

    def _flush(self, key: tuple[str, int]) -> None:
        with self._lock:
            episodes = sorted(set(self._buffer.pop(key, [])))
            self._timers.pop(key, None)
            sample = self._samples.pop(key, {})

        if not episodes:
            return

        season_number = key[1]
        episode_tags = [f"S{season_number:02}E{ep:02}" for ep in episodes]
        self._flush_callback(sample, episode_tags)
