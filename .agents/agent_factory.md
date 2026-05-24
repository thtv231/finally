# Agent: factory

## Goal

Verify the `create_market_data_source` factory function selects the correct
implementation based on the `MASSIVE_API_KEY` environment variable.

## Scope

- **Test file:** `backend/tests/market/test_factory.py`
- **Module under test:** `backend/app/market/factory.py`
- **Test class:** `TestFactory` (7 tests)

## Key scenarios

- No `MASSIVE_API_KEY` → `SimulatorDataSource`
- Empty string key → `SimulatorDataSource`
- Whitespace-only key → `SimulatorDataSource`
- Non-empty key → `MassiveDataSource`
- `MassiveDataSource` receives the API key string
- `SimulatorDataSource` receives the `PriceCache` reference
- `MassiveDataSource` receives the `PriceCache` reference

## Commands

```bash
cd /home/runner/work/finally/finally/backend
python -m pytest tests/market/test_factory.py -v --tb=short
```

## Output path

`/home/runner/work/finally/finally/.agents/results/result_factory.md`
