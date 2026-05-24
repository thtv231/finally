"""Tests for SSE streaming endpoint."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import APIRouter

from app.market.cache import PriceCache
from app.market.stream import _generate_events, create_stream_router


class TestCreateStreamRouter:
    def test_returns_api_router(self):
        cache = PriceCache()
        router = create_stream_router(cache)
        assert isinstance(router, APIRouter)

    def test_router_has_prices_route(self):
        cache = PriceCache()
        router = create_stream_router(cache)
        paths = [route.path for route in router.routes]
        assert "/prices" in paths

    def test_different_calls_return_different_routers(self):
        cache = PriceCache()
        router1 = create_stream_router(cache)
        router2 = create_stream_router(cache)
        assert router1 is not router2

    def test_router_prefix_is_api_stream(self):
        cache = PriceCache()
        router = create_stream_router(cache)
        assert router.prefix == "/api/stream"


@pytest.mark.asyncio
class TestGenerateEvents:
    async def test_first_yield_is_retry_directive(self):
        cache = PriceCache()
        request = MagicMock()
        request.client = None
        request.is_disconnected = AsyncMock(return_value=False)

        gen = _generate_events(cache, request, interval=0.001)
        first = await gen.__anext__()

        assert first == "retry: 1000\n\n"
        await gen.aclose()

    async def test_sends_data_event_when_cache_has_prices(self):
        cache = PriceCache()
        cache.update("AAPL", 190.50)

        request = MagicMock()
        request.client = None
        request.is_disconnected = AsyncMock(return_value=False)

        gen = _generate_events(cache, request, interval=0.001)
        await gen.__anext__()  # Skip retry directive

        event = await asyncio.wait_for(gen.__anext__(), timeout=1.0)

        assert event.startswith("data: ")
        await gen.aclose()

    async def test_data_event_is_valid_json(self):
        cache = PriceCache()
        cache.update("AAPL", 190.50)

        request = MagicMock()
        request.client = None
        request.is_disconnected = AsyncMock(return_value=False)

        gen = _generate_events(cache, request, interval=0.001)
        await gen.__anext__()  # Skip retry directive

        event = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        json_part = event[len("data: "):]

        payload = json.loads(json_part)
        assert isinstance(payload, dict)
        await gen.aclose()

    async def test_data_event_includes_all_cache_tickers(self):
        cache = PriceCache()
        cache.update("AAPL", 190.50)
        cache.update("GOOGL", 175.00)
        cache.update("MSFT", 420.00)

        request = MagicMock()
        request.client = None
        request.is_disconnected = AsyncMock(return_value=False)

        gen = _generate_events(cache, request, interval=0.001)
        await gen.__anext__()  # Skip retry directive

        event = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        payload = json.loads(event[len("data: "):])

        assert set(payload.keys()) == {"AAPL", "GOOGL", "MSFT"}
        await gen.aclose()

    async def test_data_event_has_correct_price_fields(self):
        cache = PriceCache()
        cache.update("AAPL", 190.50)

        request = MagicMock()
        request.client = None
        request.is_disconnected = AsyncMock(return_value=False)

        gen = _generate_events(cache, request, interval=0.001)
        await gen.__anext__()  # Skip retry directive

        event = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        payload = json.loads(event[len("data: "):])

        aapl = payload["AAPL"]
        assert aapl["ticker"] == "AAPL"
        assert aapl["price"] == 190.50
        assert "previous_price" in aapl
        assert "timestamp" in aapl
        assert "change" in aapl
        assert "change_percent" in aapl
        assert "direction" in aapl
        await gen.aclose()

    async def test_no_data_event_for_empty_cache(self):
        cache = PriceCache()

        call_count = 0

        async def mock_disconnected():
            nonlocal call_count
            call_count += 1
            return call_count >= 3

        request = MagicMock()
        request.client = None
        request.is_disconnected = mock_disconnected

        gen = _generate_events(cache, request, interval=0.001)

        events = []
        async for event in gen:
            events.append(event)

        assert events == ["retry: 1000\n\n"]

    async def test_stops_when_disconnected(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)

        call_count = 0

        async def mock_disconnected():
            nonlocal call_count
            call_count += 1
            return call_count >= 2

        request = MagicMock()
        request.client = None
        request.is_disconnected = mock_disconnected

        gen = _generate_events(cache, request, interval=0.001)

        events = []
        async for event in gen:
            events.append(event)

        assert len(events) < 5

    async def test_no_duplicate_events_when_version_unchanged(self):
        cache = PriceCache()
        cache.update("AAPL", 190.50)

        call_count = 0

        async def mock_disconnected():
            nonlocal call_count
            call_count += 1
            return call_count >= 4

        request = MagicMock()
        request.client = None
        request.is_disconnected = mock_disconnected

        gen = _generate_events(cache, request, interval=0.001)

        events = []
        async for event in gen:
            events.append(event)

        data_events = [e for e in events if e.startswith("data: ")]
        assert len(data_events) == 1

    async def test_sends_new_event_on_cache_update(self):
        cache = PriceCache()
        cache.update("AAPL", 190.50)

        request = MagicMock()
        request.client = None
        request.is_disconnected = AsyncMock(return_value=False)

        gen = _generate_events(cache, request, interval=0.001)
        await gen.__anext__()  # Retry directive

        event1 = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        payload1 = json.loads(event1[len("data: "):])
        assert payload1["AAPL"]["price"] == 190.50

        cache.update("AAPL", 191.00)

        event2 = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        payload2 = json.loads(event2[len("data: "):])
        assert payload2["AAPL"]["price"] == 191.00

        await gen.aclose()

    async def test_handles_none_client(self):
        cache = PriceCache()
        request = MagicMock()
        request.client = None
        request.is_disconnected = AsyncMock(return_value=True)

        gen = _generate_events(cache, request, interval=0.001)

        events = []
        async for event in gen:
            events.append(event)

        assert events == ["retry: 1000\n\n"]

    async def test_handles_request_with_client_host(self):
        cache = PriceCache()
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "192.168.1.100"
        request.is_disconnected = AsyncMock(return_value=True)

        gen = _generate_events(cache, request, interval=0.001)

        events = []
        async for event in gen:
            events.append(event)

        assert events == ["retry: 1000\n\n"]
