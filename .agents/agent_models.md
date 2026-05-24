# Agent: models

## Goal

Verify that all `PriceUpdate` model tests pass, covering dataclass immutability,
computed properties (`change`, `change_percent`, `direction`), and serialization.

## Scope

- **Test file:** `backend/tests/market/test_models.py`
- **Module under test:** `backend/app/market/models.py`
- **Test class:** `TestPriceUpdate` (11 tests)

## Key scenarios

- Basic creation and field access
- `change` (absolute), `change_percent` (relative), `direction` property logic
- Zero-division guard when `previous_price == 0`
- `to_dict()` serialization — all fields present and correctly typed
- Immutability: assigning to a frozen dataclass field raises `AttributeError`

## Commands

```bash
cd /home/runner/work/finally/finally/backend
python -m pytest tests/market/test_models.py -v --tb=short
```

## Output path

`/home/runner/work/finally/finally/.agents/results/result_models.md`
