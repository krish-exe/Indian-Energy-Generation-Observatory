"""Polite HTTP: one rate limiter per host, retries with backoff."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests


class PoliteSession:
    def __init__(self, user_agent: str, min_interval_s: float, timeout_s: float, retries: int):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._min_interval = min_interval_s
        self._timeout = timeout_s
        self._retries = retries
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _wait(self, url: str) -> None:
        host = urlparse(url).netloc
        with self._guard:
            lock = self._locks.setdefault(host, threading.Lock())
        with lock:
            gap = time.monotonic() - self._last.get(host, 0.0)
            if gap < self._min_interval:
                time.sleep(self._min_interval - gap)
            self._last[host] = time.monotonic()

    def request(self, method: str, url: str, **kw) -> requests.Response:
        """Returns the final response. 404 is returned, not raised: missing reports are data gaps."""
        delay = 2.0
        for attempt in range(self._retries + 1):
            self._wait(url)
            try:
                resp = self._session.request(method, url, timeout=self._timeout, **kw)
                if resp.status_code < 500 and resp.status_code != 429:
                    return resp
            except requests.RequestException:
                if attempt == self._retries:
                    raise
            time.sleep(delay)
            delay *= 2
        return resp

    def get(self, url: str, **kw) -> requests.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> requests.Response:
        return self.request("POST", url, **kw)
