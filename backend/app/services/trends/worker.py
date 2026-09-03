"""The background Trend Worker.

Kairo does not search the web at the moment you ask for a video. It keeps a
store of what it has already seen, and this is what keeps that store
current: an asyncio task started at application startup that runs a
collection pass, sleeps for the configured interval, and repeats.

Three properties it must have, because it runs unattended next to the thing
the user actually cares about:

**It must never take the app down.** Every pass is wrapped; a failure is
logged and the loop continues. There is no state in which a dead network
stops Kairo from rendering a video.

**It must not block the event loop.** A pass makes blocking HTTP calls and
SQLite writes, so it is run on a worker thread via `asyncio.to_thread`.

**It must be interruptible.** Cancellation is honoured promptly by waiting
on an event rather than sleeping, so a settings change or a shutdown does
not have to wait out a three-hour interval.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.services import settings_service
from app.services.trends import collector

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_wake: asyncio.Event | None = None
_next_run_at: datetime | None = None
_started_at: datetime | None = None

# A first pass right at startup would compete with the UI's own first
# requests, and trend data is not needed in the first seconds of a session.
_INITIAL_DELAY_SECONDS = 20.0


def next_run_at() -> datetime | None:
    return _next_run_at


def is_running() -> bool:
    return _task is not None and not _task.done()


async def _loop() -> None:
    global _next_run_at
    assert _wake is not None
    try:
        await asyncio.wait_for(_wake.wait(), timeout=_INITIAL_DELAY_SECONDS)
        _wake.clear()
    except asyncio.TimeoutError:
        pass

    while True:
        settings = settings_service.get_settings().trends
        if settings.enabled:
            try:
                result = await asyncio.to_thread(collector.collect_once)
                logger.info(
                    "Trend collection: %s (collected=%s inserted=%s updated=%s)",
                    result.get("status"),
                    result.get("collected"),
                    result.get("inserted"),
                    result.get("updated"),
                )
            except Exception:  # noqa: BLE001 - the worker outlives any single failure
                logger.exception("Trend collection pass raised")

        interval = max(30, settings_service.get_settings().trends.interval_minutes)
        _next_run_at = datetime.now(timezone.utc) + timedelta(minutes=interval)
        try:
            # Waking early is how "設定を変えたので今すぐ" and shutdown both
            # work; the timeout is the normal path.
            await asyncio.wait_for(_wake.wait(), timeout=interval * 60)
            _wake.clear()
        except asyncio.TimeoutError:
            pass


def start() -> None:
    """Starts the worker. Safe to call twice."""
    global _task, _wake, _started_at
    if is_running():
        return
    _wake = asyncio.Event()
    _started_at = datetime.now(timezone.utc)
    _task = asyncio.create_task(_loop())
    logger.info("Trend worker started")


def wake() -> None:
    """Asks the worker to run its next pass immediately."""
    if _wake is not None:
        try:
            _wake.set()
        except RuntimeError:
            logger.debug("Trend worker wake ignored: no running loop")


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _task = None
    logger.info("Trend worker stopped")


def status() -> dict:
    return {
        "running": is_running(),
        "started_at": _started_at.isoformat() if _started_at else None,
        "next_run_at": _next_run_at.isoformat() if _next_run_at else None,
    }
