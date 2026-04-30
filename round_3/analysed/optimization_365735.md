# 365735 Optimization Notes

Starting point: `round_3/runs/365735/365735.py`, restored into `round_3/submission/trader.py`.

The platform run `365735` scored `2,813.72`. Locally, the nearest comparable public-test window is round 3 day 2, timestamps `0..99900`.

## Tested Variants

The temporary test harness disabled logging only to speed up simulation. Order decisions were unchanged.

| variant | public-equivalent PnL | full day 2 PnL | all-days PnL | note |
| --- | ---: | ---: | ---: | --- |
| baseline `365735` | 2,695.0 | 18,908.0 | 61,530.0 | active all vouchers |
| no `VEV_5100` trading | 2,767.0 | 19,986.5 | 62,380.0 | removes a consistent loser |
| no `VEV_5400` trading | 2,857.0 | 18,710.0 | 61,558.0 | helps public window, weak full-day |
| no `VEV_5100`, no `VEV_5400` trading | 2,929.0 | 19,788.5 | 62,408.0 | best voucher-only change |
| no `VEV_5100`, `VEV_5400`, `VEV_5500` trading | 2,916.0 | 19,750.5 | 62,304.0 | removing `VEV_5500` was worse |
| bigger `VELVETFRUIT_EXTRACT` sizing | 2,777.0 | 21,800.0 | 65,622.5 | main edge scales well |
| bigger `VELVETFRUIT_EXTRACT` + no `VEV_5100/5400` trading | 3,011.0 | 22,680.5 | 66,500.5 | best tested variant |

## Implemented Change

`round_3/submission/trader.py` now implements the best tested variant:

- Keeps all vouchers in the IV smile fit.
- Stops actively trading `VEV_5100` and `VEV_5400`.
- Keeps trading `VEV_5200`, `VEV_5300`, and `VEV_5500`.
- Increases `VELVETFRUIT_EXTRACT` active limit from `160` to `200`.
- Increases `VELVETFRUIT_EXTRACT` base order size from `16` to `20`.

## Final Current-Code Check

| metric | PnL |
| --- | ---: |
| public-equivalent day 2, first 1,000 ticks | 3,011.0 |
| full day 2 | 22,680.5 |
| all three public days | 66,500.5 |

Public-equivalent product PnL after the change:

| product | PnL |
| --- | ---: |
| VELVETFRUIT_EXTRACT | 1,935.0 |
| HYDROGEL_PACK | 622.0 |
| VEV_5200 | 178.0 |
| VEV_4000 | 121.0 |
| VEV_5300 | 108.0 |
| VEV_6000 | 17.0 |
| VEV_6500 | 17.0 |
| VEV_5500 | 13.0 |
| VEV_4500 | 0.0 |
| VEV_5000 | 0.0 |
| VEV_5100 | 0.0 |
| VEV_5400 | 0.0 |

## Interpretation

The biggest improvement is not from the options. It is from scaling the `VELVETFRUIT_EXTRACT` mean-reversion edge. The option optimization mainly removes two public-window losers while keeping `VEV_5200` and `VEV_5300`, which were profitable in run `365735`.

The remaining risk is higher `VELVETFRUIT_EXTRACT` exposure because the active internal limit is now the full exchange limit of `200`.
