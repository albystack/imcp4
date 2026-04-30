# Backtesting

## Current layout

- `tools/prosperity4bt/`: vendored Prosperity 4 backtester.
- `.venv/`: local virtualenv with `prosperity4btest` installed.
- `backtester_resources/round3|round4|round5/`: local CSV data for each round.
- `round_3|round_4|round_5/submission/`: where each round's `trader.py` lives.
- `round_3|round_4|round_5/analysed/backtests/`: output logs from local backtests.

Round 3 data is currently staged in `backtester_resources/round3/`, copied from `round_3/raw/`.

## How it runs now

The backtester is the CLI installed from `tools/prosperity4bt`:

```sh
prosperity4btest <trader.py> <day spec> --data <data root> --out <log file> --vis
```

Example day specs:

- `3`: run all available days in round 3
- `3-0`: run only round 3 day 0
- `3-0 3-1`: run multiple specific days when calling `prosperity4btest` directly

`--vis` does not start a local frontend in this repo. It uses the backtester's built-in visualizer opener:

1. it writes a backtest log file locally
2. it starts a temporary one-file localhost server
3. it opens the hosted `jmerle` visualizer in your browser with `?open=http://localhost:...`

So the visualizer is currently the hosted site, and the backtester just hands it your local log.

## Runner script

Use:

```sh
./scripts/run_backtest.sh
```

Defaults:

- round: `3`
- day spec: `3`
- trader file: `round_3/submission/trader.py`

Examples:

```sh
./scripts/run_backtest.sh
./scripts/run_backtest.sh 3 3-0
./scripts/run_backtest.sh 3 3 --no-progress
./scripts/run_backtest.sh 3 3-0 --no-vis --no-progress
```

`--no-vis` is handled by `scripts/run_backtest.sh` itself. Use it when you only want to generate a log without opening the hosted visualizer.

For round 3, the script automatically passes the wiki position limits:

- `HYDROGEL_PACK`: `200`
- `VELVETFRUIT_EXTRACT`: `200`
- each `VEV_*` voucher: `300`

The script fails early if:

- `.venv` is missing
- `round_<n>/submission/trader.py` does not exist
- `backtester_resources/round<n>/` has no CSV files

## Current baseline

The initial round 3 strategy is in `round_3/submission/trader.py`.

Latest local historical backtest:

```text
Round 3 day 0: 17,110
Round 3 day 1: 26,486
Round 3 day 2: 21,450
Total: 65,028
Max drawdown: 10,690
```

The saved log is `round_3/analysed/backtests/round3_no_weak_mid_vouchers.log`.

The submission file intentionally has no `import` or `from ... import ...` statements. It retrieves the provided `Order` class from the `TradingState` object at runtime and uses local math helpers for the option model.
