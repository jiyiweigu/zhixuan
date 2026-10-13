"""登录失败限流（tasks.md 3.2）。

策略：以「用户名 + 客户端标识」为键的滑动窗口计数。窗口（``lock_seconds``）内失败
达到 ``max_failures`` 次即锁定，直到最早的失败记录滑出窗口。

- 键同时包含用户名与客户端，避免同一 IP 上的不同用户互相影响，
  也避免攻击者仅靠猜测用户名全局锁定他人账号。
- 进程内实现，线程安全。多进程/多实例部署时应换成 Redis 等共享存储（已知边界）。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from app.core.config import settings
from app.core.response import BizCode, BizError


class FailureLimiter:
    """按 key 记录失败时间戳的滑动窗口限流器。"""

    def __init__(
        self,
        max_failures: int | None = None,
        lock_seconds: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max(1, max_failures or settings.login_max_failures)
        self.lock_seconds = max(1, lock_seconds or settings.login_lock_seconds)
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    # —— 内部 —— #
    def _key(self, username: str, client: str) -> str:
        return f"{username.strip().lower()}|{client.strip().lower()}"

    def _prune(self, key: str, now: float) -> deque[float]:
        window = self._failures.setdefault(key, deque())
        while window and now - window[0] >= self.lock_seconds:
            window.popleft()
        return window

    # —— 对外 —— #
    def retry_after(self, username: str, client: str = "") -> int:
        """返回剩余锁定秒数，0 表示未锁定。"""
        key = self._key(username, client)
        now = self._clock()
        with self._lock:
            window = self._prune(key, now)
            if len(window) < self.max_failures:
                return 0
            return max(1, int(window[0] + self.lock_seconds - now) + 1)

    def ensure_allowed(self, username: str, client: str = "") -> None:
        """已锁定则抛出 1008（登录尝试过于频繁）。"""
        wait = self.retry_after(username, client)
        if wait > 0:
            raise BizError(
                f"登录失败次数过多，请在 {wait} 秒后重试", BizCode.TOO_MANY_ATTEMPTS
            )

    def record_failure(self, username: str, client: str = "") -> int:
        """记一次失败，返回剩余可尝试次数。"""
        key = self._key(username, client)
        now = self._clock()
        with self._lock:
            window = self._prune(key, now)
            window.append(now)
            return max(0, self.max_failures - len(window))

    def reset(self, username: str, client: str = "") -> None:
        """登录成功后清空该键的失败记录。"""
        with self._lock:
            self._failures.pop(self._key(username, client), None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()


# 全局默认实例：注册/登录共用（便于 /api/auth/* 直接依赖）
DEFAULT_LIMITER = FailureLimiter()
