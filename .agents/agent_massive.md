# Agent: massive

## Goal

Verify `MassiveDataSource` tests pass with fully mocked API calls (no real
Polygon.io requests). Tests cover the polling lifecycle, cache updates,
error handling, and ticker management.

## Scope

- **Test file:** `backend/tests/market/test_massive.py`
- **Module under test:** `backend/app/market/massive_client.py`
- **Test class:** `TestMassiveDataSource` (13 tests, asyncio)
- **Note:** All Massive REST API calls are mocked — no network access required.

## Key scenarios

- `_poll_once()` updates cache for all returned snapshots
- Malformed snapshot (None `last_trade`) is skipped; good tickers still processed
- API exception → no crash, cache unchanged for that poll
- Timestamp conversion: milliseconds → seconds (`/ 1000.0`)
- `add_ticker()` normalizes to uppercase, strips whitespace, no-op on duplicate
- `remove_ticker()` removes from list and cache
- `get_tickers()` returns current list
- Empty `_tickers` → `_fetch_snapshots` never called
- `stop()` is idempotent
- `stop()` cancels the background polling task
- `start()` does an immediate poll (cache populated before task loop begins)

## Commands

```bash
cd /home/runner/work/finally/finally/backend
python -m pytest tests/market/test_massive.py -v --tb=short
```

## Output path

`/home/runner/work/finally/finally/.agents/results/result_massive.md`
