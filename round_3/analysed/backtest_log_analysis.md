# Round 3 Backtest Log Analysis

Source logs:

- `round_3/analysed/backtests/round3_no_import_trader.log`
- `round_3/analysed/backtests/round3_no_weak_mid_vouchers.log`
- `round_3/runs/365735/365735.json`
- `round_3/runs/365735/365735.log`

## Current Strategy

The current `trader.py` has two strategy blocks.

1. Underlying mean reversion:
   - Trades `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT`.
   - Maintains an EMA of mid-price via `traderData`.
   - Adjusts fair value using top-of-book imbalance.
   - Takes liquidity when best bid/ask is far enough from fair value.
   - Also posts passive quotes around fair value with position skew.

2. Voucher IV relative-value trading:
   - Uses `VELVETFRUIT_EXTRACT` as the underlying.
   - Computes each voucher's implied volatility from the current mid.
   - Fits a quadratic smile against moneyness.
   - Converts fitted IV back to fair option price.
   - Trades vouchers when market bid/ask is far enough from model fair.
   - Does not delta hedge, because the historical/log analysis suggests the hedge cost is likely not worth it here.

The file is upload-safe under the current no-import constraint: it has no `import` or `from ... import ...` statements.

## Original Current-File Log Breakdown

This is the no-import version before disabling the weak mid-strike vouchers.

| product | day 0 | day 1 | day 2 | total |
| --- | ---: | ---: | ---: | ---: |
| HYDROGEL_PACK | 4,856 | 12,030 | 6,365 | 23,251 |
| VELVETFRUIT_EXTRACT | 9,206 | 11,386 | 12,494 | 33,087 |
| VEV_4000 | 2,748 | 2,838 | 2,720 | 8,306 |
| VEV_5000 | 200 | 190 | 0 | 390 |
| VEV_5100 | 128 | 100 | -1,078 | -850 |
| VEV_5200 | 64 | -647 | -1,307 | -1,890 |
| VEV_5300 | -30 | -468 | -612 | -1,110 |
| VEV_5400 | -182 | -44 | 198 | -28 |
| VEV_5500 | 30 | 36 | 38 | 104 |
| VEV_6000 | 45 | 45 | 45 | 135 |
| VEV_6500 | 45 | 45 | 45 | 135 |

Total PnL: `61,530`

Underlying PnL: `56,338`

Option PnL: `5,192`

## The Day-2 Mid-Strike Problem

The issue you noticed is real. On historical day 2, the mid-strike voucher cluster loses:

| product | day 2 PnL |
| --- | ---: |
| VEV_5100 | -1,078 |
| VEV_5200 | -1,307 |
| VEV_5300 | -612 |
| combined | -2,997 |

From the trade log, the strategy ended day 2 materially short these products:

| product | final net position | cash from trading | final PnL |
| --- | ---: | ---: | ---: |
| VEV_5100 | -85 | 16,049 | -1,078 |
| VEV_5200 | -90 | 9,403 | -1,307 |
| VEV_5300 | -90 | 4,608 | -612 |

The model was repeatedly willing to sell these vouchers and then carried the short inventory into a rising mark. That is bad risk because the backtester marks final inventory to mid-price, so being right intraday is not enough if we finish with a large short in a voucher whose mark moves up.

## Ablations

| variant | day 0 | day 1 | day 2 | total | note |
| --- | ---: | ---: | ---: | ---: | --- |
| current no-import trader | 17,110 | 25,512 | 18,908 | 61,530 | traded all vouchers |
| no option trading | 14,062 | 23,416 | 18,860 | 56,338 | underlyings only |
| no `VEV_5100/5200/5300` | 17,094 | 26,486 | 21,450 | 65,028 | best tested variant |
| reduced fit weight only | 16,694 | 23,914 | 17,702 | 58,310 | not enough; still trades bad shorts |

Conclusion: options are worth trading, but the weak mid-strikes are not worth trading with this model. The best tested opportunity is to keep the option layer but disable `VEV_5100`, `VEV_5200`, and `VEV_5300`.

## Platform Run 365735

Run `round_3/runs/365735` is the uploaded version before the latest patch. A diff against current `round_3/submission/trader.py` shows the only strategy change is that the uploaded file still actively traded `VEV_5100`, `VEV_5200`, and `VEV_5300`.

The platform test run is only the first 1,000 iterations of day 2 (`timestamp 0..99900`), so it is not directly comparable with the full local all-days backtest totals above.

Final platform PnL:

| product | PnL |
| --- | ---: |
| VELVETFRUIT_EXTRACT | 1,954.00 |
| HYDROGEL_PACK | 624.23 |
| VEV_5200 | 176.12 |
| VEV_4000 | 121.31 |
| VEV_5300 | 95.88 |
| VEV_4500 | 38.92 |
| VEV_5000 | 38.83 |
| VEV_6000 | 0.00 |
| VEV_6500 | 0.00 |
| VEV_5500 | -10.86 |
| VEV_5100 | -71.77 |
| VEV_5400 | -152.93 |

Total platform PnL: `2,813.72`

Final platform inventory:

| product | final position |
| --- | ---: |
| VEV_5200 | -90 |
| VEV_5300 | -90 |
| VEV_5400 | 90 |
| VELVETFRUIT_EXTRACT | 26 |
| HYDROGEL_PACK | -11 |
| VEV_5500 | 21 |
| VEV_5100 | -11 |
| VEV_5000 | 9 |
| VEV_4000 | 4 |
| VEV_4500 | -1 |

This explains why the platform score can look acceptable while the full-day local test exposed the problem. In the first 1,000 iterations, the removed mid-strikes were not yet bad enough to hurt total PnL. Over the full historical day 2, the same old model finished with large short `VEV_5100/5200/5300` exposure and lost almost `3,000` on those three products. The patch is therefore a risk-control improvement for the longer final simulation, not a guaranteed improvement to the short public upload test.

## Patched Trader Result

The real `round_3/submission/trader.py` now excludes `VEV_5100`, `VEV_5200`, and `VEV_5300` from its active voucher list.

| product | day 0 | day 1 | day 2 | total |
| --- | ---: | ---: | ---: | ---: |
| HYDROGEL_PACK | 4,856 | 12,030 | 6,365 | 23,251 |
| VELVETFRUIT_EXTRACT | 9,206 | 11,386 | 12,494 | 33,087 |
| VEV_4000 | 2,748 | 2,838 | 2,720 | 8,306 |
| VEV_5000 | 0 | -30 | 0 | -30 |
| VEV_5400 | 177 | 176 | -294 | 59 |
| VEV_5500 | 16 | -4 | 87 | 99 |
| VEV_6000 | 45 | 45 | 45 | 135 |
| VEV_6500 | 45 | 45 | 32 | 122 |

Total PnL: `65,028`

Underlying PnL: `56,338`

Option PnL: `8,690`

Improvement vs previous no-import trader: `+3,498`

## Opportunities

1. Keep `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT` active. They are the main edge, contributing `56,338` across the three historical days.
2. Keep `VEV_4000` active. It is the only voucher with consistently large positive contribution: `8,306`.
3. Avoid `VEV_5100`, `VEV_5200`, and `VEV_5300` for now. The old model creates large short exposure there and loses almost `3,000` on historical day 2 alone.
4. `VEV_5400`, `VEV_5500`, `VEV_6000`, and `VEV_6500` are small contributors. They are not the main edge, but after removing the bad mid-strikes they do not materially harm the total.
5. The next serious improvement would be a separate fair-value rule for deep ITM `VEV_4000`, because the current option system needs enough strikes to fit the smile. If we isolate that product too aggressively, the current model stops trading options entirely.
