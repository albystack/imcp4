# IMC Prosperity Overview

This repository captures my work on the IMC Prosperity competition across rounds 3 to 5. The strategy evolved from a round-3 core of underlying mean reversion plus option pricing, into a round-4 extension that used counterparty information and more refined option surface fitting, and finally into a round-5 portfolio that cherry-picked only the products with repeatable edge.

The tutorial and the first two rounds established the mechanics and market conventions; the detailed implementation work in this repo starts at the round-3 reset and carries through the final round.

## Competition Context

Prosperity is a market simulation where each round introduces a new set of tradable products, position limits, and sometimes a separate manual-trading challenge. The main objective is always the same: identify exploitable structure in the market data, encode it into a trader, and manage inventory risk well enough that profits survive the final marking process.

In this workspace, the relevant round structure is:

- Round 3: Hydrogel Packs, Velvetfruit Extract, and Velvetfruit Extract Vouchers.
- Round 4: the same core products, but with counterparty identities visible in the trade stream, plus a separate manual Aether Crystal options challenge.
- Round 5: a completely new product universe, plus a manual final-round challenge on Ignith goods and Ashflow Alpha news.

## Round 3

Round 3 was the starting point for the main trading framework. The key idea was to treat `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT` as the two underlyings, then value the voucher strip through an implied-volatility smile.

The round-3 trader combined two ideas:

- Mean reversion and light market making on the underlyings, especially `VELVETFRUIT_EXTRACT`.
- Black-Scholes pricing and implied-volatility fitting for the voucher set, with relative-value trading around the fitted fair values.

The analysis notes show that the platform run `365735` achieved `2,813.72` on the public-test slice, while the full local historical backtest reached `61,530` for the baseline and `65,028` after a patch that removed some weak mid-strike voucher exposure. The main lesson was that most of the edge came from the underlyings, and that voucher inventory could become the main risk if it was left too concentrated.

What I did in this round:

- Restored the strategy from the saved run into the submission trader.
- Fit an option surface over voucher implied volatilities using Black-Scholes inversion and a quadratic smile.
- Used an EMA-based fair value for the underlyings, with inventory-aware quoting.
- Tuned the voucher set to avoid weak strikes and reduce drawdown risk.

## Round 4

Round 4 kept the same core products but added a much more informative market tape: counterparty names were visible in the historical trades. That made it possible to reason about who was consistently toxic, who was providing edge, and where markout patterns existed.

The round-4 trader extended the round-3 framework in three ways:

- Counterparty-aware signal tracking on the underlying products.
- A more deliberate warmup and inventory management policy for `VELVETFRUIT_EXTRACT`.
- The same option-surface machinery for the voucher strip, but with more selective quoting and delta-aware fair values.

The round-4 notes in this repository are mostly notebook-based, but the code path shows the structural changes clearly: memory now stores additional signal state, the trader waits before actively trading `VELVETFRUIT_EXTRACT` early in the day, and voucher pricing is adjusted using fitted deltas so that inventory is accounted for more explicitly.

The manual challenge in round 4 was a separate Aether Crystal options problem. The prompt introduced vanilla options and exotics such as chooser, binary put, and knock-out put. The important takeaway for the repository is that round 4 broadened the workflow from pure algorithmic trading into a mix of algorithmic and manual allocation problems.

What I did in this round:

- Reused the round-3 pricing core instead of starting over.
- Added counterparty-aware logic from the newly visible buyer and seller identities.
- Refined the underlying trading logic with explicit inventory skew and fair-value adjustment.
- Kept the option workflow centered on implied volatility, but made it more conservative and stateful.

## Round 5

Round 5 was a full reset into a new market with 50 entirely new products, plus a manual challenge on Ignith goods using Ashflow Alpha news. The prompt was effectively a product-selection problem: identify the few names with repeatable inefficiency and ignore the rest.

The final trader in `round_5/submission/trader_round5.py` therefore became much more selective. The strategy was no longer trying to trade everything; it was explicitly cherry-picking the winners.

The main round-5 components were:

- Strong mean-reversion takers on `ROBOT_DISHES` and `OXYGEN_SHAKE_EVENING_BREATH` using EWMA fair values.
- A basket-based signal on the `PEBBLES` family, used as a market-making skew rather than a crossing arbitrage.
- A pair trade on `SNACKPACK_CHOCOLATE` and `SNACKPACK_VANILLA` with a slow adaptive target.
- Wide-spread market making on the `SNACKPACK` family, selected `OXYGEN_SHAKE_CHOCOLATE`, and two profitable translator names.
- Explicit avoidance of product groups that backtested as weak or unstable.

The strategy summary in the code documents the selection logic directly: the good edge was in a small subset of products, not in blanket coverage. That was the central lesson from round 5.

The manual final-round prompt also introduced a budgeted Ashflow Alpha portfolio task. The important feature there was that trade size had a nonlinear fee, so the allocation problem was about reading news critically and sizing exposure carefully rather than simply going long every apparently positive headline.

What I did in this round:

- Filtered the product universe down to a handful of repeatable signals.
- Mixed taker, market-making, and pair-trade logic instead of relying on a single alpha source.
- Used basket and pair relationships to skew quotes rather than forcing arbitrage.
- Left out product families that were backtested as negative or too noisy.

## Strategy Evolution

Across the three rounds, the strategy evolved in a clear direction:

1. Round 3 established the core model: underlying mean reversion plus option pricing.
2. Round 4 made that model stateful and counterparty-aware.
3. Round 5 turned the whole approach into a product-selection engine, where only the best signals were kept.

The repeated pattern was:

- Build a fair value model.
- Measure how the market deviates from it.
- Trade only when the deviation is large enough to survive spread, fees, and inventory risk.
- Reduce exposure when a product is noisy, unstable, or not worth the capital.

## Files That Capture The Work

- [Round 3 analysis](round_3/analysed/run_365735_analysis.md)
- [Round 3 optimization notes](round_3/analysed/optimization_365735.md)
- [Round 3 trader](round_3/submission/trader.py)
- [Round 4 prompt](round_4/wiki/round4.md)
- [Round 4 trader](round_4/submission/trader.py)
- [Round 5 prompt](round_5/wiki/wiki.md)
- [Round 5 trader](round_5/submission/trader_round5.py)
- [Backtesting guide](BACKTESTING.md)

## Short Version

The competition story in this repository is: start with a robust round-3 underlier-and-options framework, expand it with counterparty intelligence in round 4, then finish by selecting only the round-5 product groups that produced repeatable edge. The final shape of the work is less about trading everything and more about knowing what to ignore.