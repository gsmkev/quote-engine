import asyncio
from unittest.mock import AsyncMock, patch

from quote_engine import worker
from quote_engine.config import Settings
from quote_engine.domain.catalog import Catalog


async def test_loop_survives_errors_sleeps_when_idle_and_stops():
    stop = asyncio.Event()
    calls = []

    async def fake(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        if len(calls) == 3:
            stop.set()
        return len(calls) == 2  # busy once, then idle

    s = Settings(poll_interval_s=0.01)
    with patch.object(worker, "process_next", AsyncMock(side_effect=fake)):
        await asyncio.wait_for(worker.run(None, None, Catalog(items={}), s, stop), 2)  # ty: ignore[invalid-argument-type]
    assert len(calls) == 3
