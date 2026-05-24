# Agent: stream

## Goal

Verify `create_stream_router` and `_generate_events` tests pass: SSE formatting,
version-based deduplication, disconnection handling, and live price delivery.

## Scope

- **Test file:** `backend/tests/market/test_stream.py`
- **Module under test:** `backend/app/market/stream.py`
- **Test classes:** `TestCreateStreamRouter` (4 tests), `TestGenerateEvents` (10 tests, asyncio)

## Key scenarios

**Router:**
- Returns `APIRouter` instance with `/prices` route
- Router prefix is `/api/stream`
- Each call returns a new, distinct router object

**Event generator:**
- First yield is always `"retry: 1000\n\n"`
- Sends `data: {...}` event when cache is non-empty
- Payload is valid JSON with all tickers as top-level keys
- Each ticker dict has required fields: ticker, price, previous_price, timestamp, change, change_percent, direction
- Empty cache → no `data:` events (only retry directive)
- Stops iteration on client disconnect
- No duplicate events when cache version unchanged
- New event emitted when cache is updated
- Handles `request.client = None` (no crash)
- Handles request with actual client host string

## Commands

```bash
cd /home/runner/work/finally/finally/backend
python -m pytest tests/market/test_stream.py -v --tb=short
```

## Output path

`/home/runner/work/finally/finally/.agents/results/result_stream.md`
