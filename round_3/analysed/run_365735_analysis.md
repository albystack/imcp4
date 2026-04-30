# Run 365735 Analysis

Source files:

- `round_3/runs/365735/365735.py`
- `round_3/runs/365735/365735.json`
- `round_3/runs/365735/365735.log`

## Result

Run `365735` finished successfully with platform PnL `2,813.72`.

The run covers public test day `2`, timestamps `0..99900`, i.e. the 1,000-iteration platform test rather than the full local historical day.

## Strategy Implemented

The strategy restored in `round_3/submission/trader.py` is the exact trading logic from `round_3/runs/365735/365735.py`.

It has two components:

1. Underlying mean reversion and market making on `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT`.
2. Voucher IV relative-value trading on all vouchers, including `VEV_5100`, `VEV_5200`, and `VEV_5300`.

The restored file has no `import` or `from ... import ...` statements and compiles successfully.

## Final Product PnL

| product | final PnL |
| --- | ---: |
| VELVETFRUIT_EXTRACT | 1,954.00 |
| HYDROGEL_PACK | 624.23 |
| VEV_5200 | 176.12 |
| VEV_4000 | 121.31 |
| VEV_5300 | 95.88 |
| VEV_4500 | 38.92 |
| VEV_5000 | 38.83 |
| VEV_6500 | 0.00 |
| VEV_6000 | 0.00 |
| VEV_5500 | -10.86 |
| VEV_5100 | -71.77 |
| VEV_5400 | -152.93 |

Main edge in this run:

- `VELVETFRUIT_EXTRACT` plus `HYDROGEL_PACK`: `2,578.23`
- vouchers combined: `235.49`

So the platform-test score is mostly coming from the two underlyings, not the option layer.

## Final Inventory

| product | final position |
| --- | ---: |
| HYDROGEL_PACK | -11 |
| VELVETFRUIT_EXTRACT | 26 |
| VEV_4000 | 4 |
| VEV_4500 | -1 |
| VEV_5000 | 9 |
| VEV_5100 | -11 |
| VEV_5200 | -90 |
| VEV_5300 | -90 |
| VEV_5400 | 90 |
| VEV_5500 | 21 |

The largest risk is still voucher inventory: `VEV_5200 = -90`, `VEV_5300 = -90`, and `VEV_5400 = +90`.

## Drawdown

Total PnL reached:

- Minimum: `-247.33` at timestamp `6200`
- Maximum: `3,172.92` at timestamp `95800`
- Final: `2,813.72`

This is a strong public-test curve, but it gives back about `359` from peak into the close.

## Trade Summary

| product | final pos | cash | bought | sold | submission trade count |
| --- | ---: | ---: | ---: | ---: | ---: |
| HYDROGEL_PACK | -11 | 110,182 | 12 | 23 | 8 |
| VELVETFRUIT_EXTRACT | 26 | -134,912 | 223 | 197 | 44 |
| VEV_4000 | 4 | -4,935 | 9 | 5 | 7 |
| VEV_4500 | -1 | 803 | 4 | 5 | 5 |
| VEV_5000 | 9 | -2,366 | 9 | 0 | 4 |
| VEV_5100 | -11 | 1,864 | 1 | 12 | 2 |
| VEV_5200 | -90 | 9,406 | 0 | 90 | 11 |
| VEV_5300 | -90 | 4,608 | 0 | 90 | 9 |
| VEV_5400 | 90 | -1,602 | 90 | 0 | 9 |
| VEV_5500 | 21 | -147 | 21 | 0 | 4 |

## Conclusion

For maximizing the short public upload test score, run `365735` is the better reference than the later patched strategy. The patched strategy removed mid-strike voucher risk, but that risk was not punished in the short public test.

For the final longer simulation, the same inventory can still be dangerous. If we prioritize the public test signal, keep the restored `365735` logic. If we prioritize robust full-day backtests, reduce or cap the mid-strike voucher inventory before submission.
