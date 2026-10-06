from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


class Saga:
    """Run an external side effect with reverse-order compensations on failure."""

    @staticmethod
    async def run(action: Callable[[], Awaitable[T]], compensations: list[Callable[[], Awaitable[None]]]) -> T:
        try:
            return await action()
        except BaseException:
            for compensate in reversed(compensations):
                try:
                    await compensate()
                except Exception:
                    logger.exception("Saga compensation failed")
            raise
