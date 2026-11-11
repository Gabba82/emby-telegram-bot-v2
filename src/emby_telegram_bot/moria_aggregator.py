from __future__ import annotations

import logging
import threading
from typing import Any, Callable


class MoriaBatchAggregator:
    def __init__(
        self,
        flush_delay_seconds: int,
        flush_movies_callback: Callable[[list[dict[str, Any]]], None],
        flush_series_callback: Callable[[list[dict[str, Any]]], None],
    ) -> None:
        self._flush_delay_seconds = flush_delay_seconds
        self._flush_movies_callback = flush_movies_callback
        self._flush_series_callback = flush_series_callback
        self._movies: dict[str, dict[str, Any]] = {}
        self._episodes: dict[str, dict[str, Any]] = {}
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def add_movie(self, item: dict[str, Any]) -> None:
        item_id = str(item.get("Id") or len(self._movies))
        with self._lock:
            self._movies[item_id] = dict(item)
            self._reset_timer_locked()

    def add_episode(self, item: dict[str, Any]) -> None:
        item_id = str(item.get("Id") or len(self._episodes))
        with self._lock:
            self._episodes[item_id] = dict(item)
            self._reset_timer_locked()

    def pending_count(self) -> tuple[int, int]:
        with self._lock:
            return len(self._movies), len(self._episodes)

    def _reset_timer_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        timer = threading.Timer(self._flush_delay_seconds, self._flush)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def flush_now(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._flush()

    def _flush(self) -> None:
        with self._lock:
            self._timer = None
            movies = list(self._movies.values())
            self._movies.clear()
            episodes = list(self._episodes.values())
            self._episodes.clear()

        if movies:
            try:
                self._flush_movies_callback(movies)
            except Exception as exc:
                logging.error("Moria movies batch flush failed error=%s", exc)

        if episodes:
            try:
                self._flush_series_callback(episodes)
            except Exception as exc:
                logging.error("Moria series batch flush failed error=%s", exc)
