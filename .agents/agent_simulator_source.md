# Agent: simulator_source

## Goal

Run integration tests for `SimulatorDataSource` — the `MarketDataSource`
implementation wrapping `GBMSimulator`. Tests exercise the full asyncio
lifecycle: start, update, add/remove tickers, stop.

## Scope

- **Test file:** `backend/tests/market/test_simulator_source.py`
- **Module under test:** `backend/app/market/simulator.py` (`SimulatorDataSource` class)
- **Test class:** `TestSimulatorDataSource` (10 tests, asyncio)

## Key scenarios

- `start()` seeds cache immediately with initial prices
- Cache version increments over multiple update cycles (background loop)
- `stop()` is clean and idempotent (double-stop no exception)
- `add_ticker()` → ticker appears in list and cache immediately
- `remove_ticker()` → ticker removed from list and cache
- `get_tickers()` returns the live set
- Empty `start([])` → empty cache, empty ticker list
- Task remains running after an exception inside the loop
- Custom `update_interval` produces faster updates
- `event_probability=1.0` (always trigger) starts and stops cleanly

## Commands

```bash
cd /home/runner/work/finally/finally/backend
python -m pytest tests/market/test_simulator_source.py -v --tb=short
```

## Output path

`/home/runner/work/finally/finally/.agents/results/result_simulator_source.md`
