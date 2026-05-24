# Market Data Test Orchestrator

## Overview

Runs the full market data test suite for `backend/app/market/` in parallel
using one agent per test module. Each agent installs dependencies, runs its
assigned test file, and writes a structured result to `.agents/results/`.

## Agents

| Agent | Test file | Module under test |
|-------|-----------|-------------------|
| `models` | `tests/market/test_models.py` | `app/market/models.py` |
| `cache` | `tests/market/test_cache.py` | `app/market/cache.py` |
| `simulator` | `tests/market/test_simulator.py` | `app/market/simulator.py` (GBMSimulator) |
| `simulator_source` | `tests/market/test_simulator_source.py` | `app/market/simulator.py` (SimulatorDataSource) |
| `factory` | `tests/market/test_factory.py` | `app/market/factory.py` |
| `massive` | `tests/market/test_massive.py` | `app/market/massive_client.py` |
| `stream` | `tests/market/test_stream.py` | `app/market/stream.py` |

## Strategy

1. All agents launch in parallel (no inter-agent dependencies).
2. Each agent:
   a. `cd backend/`
   b. Installs deps: `pip install -e ".[dev]"` or `uv sync --dev`
   c. Runs: `python -m pytest <test_file> -v --tb=short --co -q` (collect only to
      verify discovery) then the full run.
   d. Writes `../.agents/results/result_<name>.md`.
3. Orchestrator collects all result files, synthesises findings into
   `planning/MARKET_DATA_REVIEW.md`.

## Commands (per agent)

```bash
cd /home/runner/work/finally/finally/backend
python -m pytest tests/market/test_<name>.py -v --tb=short 2>&1
```

## Output path

Each agent writes: `.agents/results/result_<name>.md`

## Completion criteria

- All 7 result files present.
- Review doc written to `planning/MARKET_DATA_REVIEW.md`.
- PR opened with branch `review/market-data`.
