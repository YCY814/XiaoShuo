"""带重试与限速的 HTTP 取页面工具。"""

from __future__ import annotations

import logging
import random
import time

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 各站点限流时返回的状态码，需要退避重试而不是直接放弃
THROTTLED_STATUS = {403, 429, 503}


class Fetcher:
    """单站点共用一个 Session，失败重试后返回 None（由调用方决定降级）。"""

    def __init__(
        self, delay: float = 0.6, timeout: int = 15, max_retry: int = 3, backoff: float = 5.0
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.max_retry = max_retry
        # 403/429 是被限流的信号，此时等得更久才有意义
        self.backoff = backoff
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            }
        )

    def get(self, url: str, **kwargs) -> str | None:
        for attempt in range(self.max_retry + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
                if resp.status_code == 200:
                    resp.encoding = resp.encoding or "utf-8"
                    time.sleep(self.delay * random.uniform(0.7, 1.3))
                    return resp.text

                logger.warning("HTTP %s <- %s", resp.status_code, url)
                if resp.status_code in THROTTLED_STATUS and attempt < self.max_retry:
                    time.sleep(self.backoff * (attempt + 1) * random.uniform(0.8, 1.2))
                    continue
                return None
            except Exception as exc:  # noqa: BLE001 - 单站点失败必须被隔离
                logger.warning("请求失败(%s/%s) %s: %s", attempt + 1, self.max_retry + 1, url, exc)
                time.sleep(self.delay)
        return None
