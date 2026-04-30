from __future__ import annotations

from pathlib import Path

import nbformat as nbf


NOTEBOOK_PATH = Path(__file__).with_name("round_4_analysis.ipynb")


def md(text: str):
    return nbf.v4.new_markdown_cell(text.strip() + "\n")


def code(text: str):
    return nbf.v4.new_code_cell(text.strip() + "\n")


cells = [
    md(
        r"""
# Round 4 Analysis Notebook

This notebook analyses the Round 4 data capsule in `round_4/raw/` and saves figures into `round_4/graphs/`.

## Wiki summary

Round 4 is **not** the same product setup as last year's location-arbitrage macarons example. The wiki says the algorithmic challenge is a counterparty-information round:

- `HYDROGEL_PACK`, position limit 200
- `VELVETFRUIT_EXTRACT`, position limit 200
- `VELVETFRUIT_EXTRACT_VOUCHER`, ten vouchers, position limit 300 per voucher
- Historical trades now expose `buyer` and `seller` IDs, e.g. `Mark 01`, `Mark 22`, etc.

The key edge to search for is therefore **who trades profitably**, not import/export conversion arbitrage. This notebook focuses on:

1. Market structure of the delta-1 products.
2. Voucher pricing surface and residuals against a simple call model.
3. Counterparty behavior: trade direction, volume, pair flow, and future markout.
4. Actionable signals that can be turned into a `trader.py`.

## Working hypotheses

- `HYDROGEL_PACK` may still be a wide-spread mean-reversion product.
- `VELVETFRUIT_EXTRACT` is the underlying for all `VEV_*` vouchers and should drive option fair values.
- Some `Mark XX` counterparties may be informed or systematically exploitable.
- The strongest Round 4 improvement over Round 3 should come from combining the old price/model signals with counterparty-conditioned signals.
"""
    ),
    code(
        r"""
from pathlib import Path
import math
import warnings

import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from scipy.stats import norm
import statsmodels.api as sm
from IPython.display import display, Markdown

warnings.filterwarnings("ignore")

sns.set_theme(style="whitegrid", context="talk")
plt.rcParams["figure.figsize"] = (15, 7)
plt.rcParams["axes.titlesize"] = 16
plt.rcParams["axes.labelsize"] = 13

CWD = Path.cwd()
if (CWD / "raw").exists():
    ROUND_DIR = CWD
elif (CWD.parent / "raw").exists():
    ROUND_DIR = CWD.parent
else:
    ROUND_DIR = Path("/Users/alberto/Desktop/competitions/imcp4/round_4")

RAW_DIR = ROUND_DIR / "raw"
WIKI_DIR = ROUND_DIR / "wiki"
ANALYSED_DIR = ROUND_DIR / "analysed"
GRAPHS_DIR = ROUND_DIR / "graphs"
ANALYSED_DIR.mkdir(parents=True, exist_ok=True)
GRAPHS_DIR.mkdir(parents=True, exist_ok=True)

UNDERLYINGS = ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"]
VOUCHERS = ["VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500"]
ALL_PRODUCTS = UNDERLYINGS + VOUCHERS
STRIKES = {p: int(p.split("_")[1]) for p in VOUCHERS}

# The wiki explicitly says a VEV_5000 voucher has TTE=4 days in Round 4.
# We use 4 trading days as the main mapping, and later include sensitivity checks.
T_MAIN = 4 / 365
SIGMA_GRID = np.linspace(0.01, 1.5, 350)


def savefig(name: str):
    plt.savefig(GRAPHS_DIR / name, dpi=160, bbox_inches="tight")


def clean_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "day", "timestamp", "bid_price_1", "bid_volume_1", "bid_price_2", "bid_volume_2",
        "bid_price_3", "bid_volume_3", "ask_price_1", "ask_volume_1", "ask_price_2",
        "ask_volume_2", "ask_price_3", "ask_volume_3", "mid_price", "profit_and_loss",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["is_voucher"] = df["product"].str.startswith("VEV_")
    df["strike"] = df["product"].map(STRIKES)
    df["spread"] = df["ask_price_1"] - df["bid_price_1"]
    df.loc[(df["bid_price_1"] <= 0) | (df["ask_price_1"] <= 0), "spread"] = np.nan
    df["top_depth"] = df["bid_volume_1"].fillna(0).abs() + df["ask_volume_1"].fillna(0).abs()
    df["book_empty"] = (df["bid_price_1"].fillna(0) <= 0) | (df["ask_price_1"].fillna(0) <= 0)
    df["global_timestamp"] = (df["day"] - df["day"].min()) * 1_000_000 + df["timestamp"]
    return df


def clean_trade_frame(df: pd.DataFrame, day: int) -> pd.DataFrame:
    df = df.copy()
    df["day"] = day
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype(int)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype(int)
    df["notional"] = df["price"] * df["quantity"]
    df["is_voucher"] = df["symbol"].str.startswith("VEV_")
    df["strike"] = df["symbol"].map(STRIKES)
    df["global_timestamp"] = (df["day"] - 1) * 1_000_000 + df["timestamp"]
    return df


def bs_call_price(S, K, T, sigma):
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    T = np.maximum(float(T), 1e-9)
    d1 = (np.log(np.maximum(S, 1e-9) / K) + 0.5 * sigma**2 * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * norm.cdf(d2)


def best_fit_sigma(S, strikes, market_prices, T=T_MAIN):
    strikes = np.asarray(strikes, dtype=float)
    market_prices = np.asarray(market_prices, dtype=float)
    model = np.array([bs_call_price(S, strikes, T, sig) for sig in SIGMA_GRID])
    err = ((model - market_prices[None, :]) ** 2).mean(axis=1)
    idx = int(np.argmin(err))
    return float(SIGMA_GRID[idx]), model[idx]


def add_future_mids_to_trades(trades: pd.DataFrame, prices: pd.DataFrame, horizons=(100, 500, 1000, 5000, 10000)) -> pd.DataFrame:
    out = trades.copy()
    mids = prices[["day", "timestamp", "product", "mid_price"]].rename(columns={"product": "symbol"})
    for h in horizons:
        future = mids.copy()
        future["timestamp"] = future["timestamp"] - h
        future = future.rename(columns={"mid_price": f"mid_fwd_{h}"})
        out = out.merge(future, on=["day", "timestamp", "symbol"], how="left")
        out[f"buyer_edge_{h}"] = out[f"mid_fwd_{h}"] - out["price"]
        out[f"seller_edge_{h}"] = out["price"] - out[f"mid_fwd_{h}"]
        out[f"buyer_edge_notional_{h}"] = out[f"buyer_edge_{h}"] * out["quantity"]
        out[f"seller_edge_notional_{h}"] = out[f"seller_edge_{h}"] * out["quantity"]
    return out
"""
    ),
    md("## Load And Validate Data"),
    code(
        r"""
price_files = sorted(RAW_DIR.glob("prices_round_4_day_*.csv"))
trade_files = sorted(RAW_DIR.glob("trades_round_4_day_*.csv"))

prices = pd.concat(
    [clean_price_frame(pd.read_csv(path, sep=";")).assign(source_file=path.name) for path in price_files],
    ignore_index=True,
)

trades = pd.concat(
    [
        clean_trade_frame(pd.read_csv(path, sep=";"), int(path.stem.split("_")[-1])).assign(source_file=path.name)
        for path in trade_files
    ],
    ignore_index=True,
)

print(f"Loaded {len(prices):,} price rows from {len(price_files)} files")
print(f"Loaded {len(trades):,} trade rows from {len(trade_files)} files")
print("Products:", ", ".join(sorted(prices["product"].unique())))
print("Counterparties:", trades["buyer"].nunique(), "buyers,", trades["seller"].nunique(), "sellers,", len(set(trades["buyer"]) | set(trades["seller"])), "unique IDs")

display(prices.head())
display(trades.head())
"""
    ),
    code(
        r"""
capsule_summary = pd.DataFrame(
    {
        "price_rows": prices.groupby("source_file").size(),
        "trade_rows": trades.groupby("source_file").size(),
    }
).fillna(0).astype(int)

product_day_counts = prices.groupby(["day", "product"]).size().unstack(fill_value=0)
trade_day_counts = trades.groupby(["day", "symbol"]).size().unstack(fill_value=0)

display(Markdown("### Data capsule files"))
display(capsule_summary)
display(Markdown("### Price rows per product/day"))
display(product_day_counts)
display(Markdown("### Trade rows per product/day"))
display(trade_day_counts)
"""
    ),
    md(
        r"""
### Initial read

Each price day contains 10,000 timestamps for 12 products, so the data is a complete quote panel. Trade prints are much sparser, and that matters: quote-based signals are reliable at every tick, while counterparty signals only update when someone trades.
"""
    ),
    md("## Market Structure Overview"),
    code(
        r"""
summary = prices.groupby("product").agg(
    rows=("mid_price", "size"),
    days=("day", "nunique"),
    mean_mid=("mid_price", "mean"),
    std_mid=("mid_price", "std"),
    min_mid=("mid_price", "min"),
    max_mid=("mid_price", "max"),
    mean_spread=("spread", "mean"),
    median_spread=("spread", "median"),
    mean_top_depth=("top_depth", "mean"),
    empty_book_rows=("book_empty", "sum"),
).reset_index()
summary["strike"] = summary["product"].map(STRIKES)
summary = summary.sort_values(["strike", "product"], na_position="first")

trade_summary = trades.groupby("symbol").agg(
    trades=("price", "size"),
    total_qty=("quantity", "sum"),
    total_notional=("notional", "sum"),
    mean_trade_price=("price", "mean"),
    mean_trade_qty=("quantity", "mean"),
    unique_buyers=("buyer", "nunique"),
    unique_sellers=("seller", "nunique"),
).reset_index().rename(columns={"symbol": "product"})

overview = summary.merge(trade_summary, on="product", how="left").fillna({"trades": 0, "total_qty": 0, "total_notional": 0})
display(overview.round(3))

overview.to_csv(ANALYSED_DIR / "round4_product_overview.csv", index=False)
"""
    ),
    code(
        r"""
fig, axes = plt.subplots(2, 1, figsize=(16, 11), sharex=True)
for ax, product in zip(axes, UNDERLYINGS):
    subset = prices[prices["product"] == product].copy()
    sns.lineplot(data=subset, x="timestamp", y="mid_price", hue="day", palette="viridis", linewidth=1, ax=ax)
    ax.set_title(f"{product} mid-price paths by day")
    ax.set_ylabel("Mid price")
    ax.legend(title="day")
axes[-1].set_xlabel("Timestamp")
plt.tight_layout()
savefig("round4_underlying_price_paths.png")
plt.show()
"""
    ),
    code(
        r"""
underlying = prices[prices["product"].isin(UNDERLYINGS)].copy()

fig, axes = plt.subplots(1, 3, figsize=(19, 6))
sns.boxplot(data=underlying, x="product", y="spread", ax=axes[0])
axes[0].set_title("Top-of-book spread distribution")
axes[0].tick_params(axis="x", rotation=15)

sns.boxplot(data=underlying, x="product", y="top_depth", ax=axes[1])
axes[1].set_title("Top-of-book displayed depth")
axes[1].tick_params(axis="x", rotation=15)

empty = prices.groupby(["product", "day"])["book_empty"].sum().reset_index()
sns.barplot(data=empty, x="product", y="book_empty", hue="day", ax=axes[2])
axes[2].set_title("Empty or one-sided book rows")
axes[2].tick_params(axis="x", rotation=90)
plt.tight_layout()
savefig("round4_liquidity_spread_depth_empty_books.png")
plt.show()
"""
    ),
    code(
        r"""
wide_mid = prices.pivot_table(index=["day", "timestamp"], columns="product", values="mid_price")
returns = wide_mid.groupby(level=0).diff()

underlying_return_stats = []
for product in UNDERLYINGS:
    r = returns[product].dropna()
    for lag in range(1, 11):
        underlying_return_stats.append(
            {
                "product": product,
                "lag": lag,
                "autocorr": r.autocorr(lag),
            }
        )
autocorr_df = pd.DataFrame(underlying_return_stats)

fig, ax = plt.subplots(figsize=(13, 6))
sns.lineplot(data=autocorr_df, x="lag", y="autocorr", hue="product", marker="o", ax=ax)
ax.axhline(0, color="black", linewidth=1)
ax.set_title("Lagged return autocorrelation")
ax.set_ylabel("Return autocorrelation")
plt.tight_layout()
savefig("round4_underlying_return_autocorrelation.png")
plt.show()

display(autocorr_df.pivot(index="lag", columns="product", values="autocorr").round(4))
"""
    ),
    code(
        r"""
imbalance_rows = []
for product in UNDERLYINGS:
    df = prices[prices["product"] == product].sort_values(["day", "timestamp"]).copy()
    denom = df["bid_volume_1"].abs() + df["ask_volume_1"].abs()
    df["imbalance"] = np.where(denom > 0, (df["bid_volume_1"].fillna(0) - df["ask_volume_1"].abs().fillna(0)) / denom, np.nan)
    df["next_mid_change"] = df.groupby("day")["mid_price"].shift(-1) - df["mid_price"]
    df["product"] = product
    imbalance_rows.append(df[["day", "timestamp", "product", "imbalance", "next_mid_change"]])
imbalance = pd.concat(imbalance_rows, ignore_index=True).dropna()

imbalance_summary = imbalance.groupby("product").apply(
    lambda g: pd.Series(
        {
            "corr_imbalance_next_move": g["imbalance"].corr(g["next_mid_change"]),
            "mean_next_move": g["next_mid_change"].mean(),
            "std_next_move": g["next_mid_change"].std(),
        }
    )
)
display(imbalance_summary.round(5))

imbalance["bucket"] = pd.qcut(imbalance["imbalance"], 10, duplicates="drop")
bucketed = imbalance.groupby(["product", "bucket"], observed=True)["next_mid_change"].agg(["mean", "count"]).reset_index()
bucketed["bucket_mid"] = bucketed["bucket"].apply(lambda x: x.mid)

fig, axes = plt.subplots(1, 2, figsize=(17, 6), sharey=True)
for ax, product in zip(axes, UNDERLYINGS):
    sub = bucketed[bucketed["product"] == product]
    sns.lineplot(data=sub, x="bucket_mid", y="mean", marker="o", ax=ax)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title(f"{product}: next move by imbalance decile")
    ax.set_xlabel("Imbalance bucket midpoint")
    ax.set_ylabel("Mean next mid change")
plt.tight_layout()
savefig("round4_imbalance_predictive_power.png")
plt.show()
"""
    ),
    md(
        r"""
### Delta-1 interpretation

This section should be used directly for the underlyings strategy:

- A negative lag-1 return autocorrelation supports taking stretched quotes back toward fair.
- A positive imbalance-to-next-move relationship supports skewing passive quotes with top-book imbalance.
- Spread and depth distributions define how far from fair we need to quote to avoid adverse selection.
"""
    ),
    md("## Trade And Counterparty Overview"),
    code(
        r"""
fig, axes = plt.subplots(1, 2, figsize=(18, 7))
trade_counts = trades.groupby(["day", "symbol"]).size().reset_index(name="trades")
sns.barplot(data=trade_counts, x="symbol", y="trades", hue="day", ax=axes[0])
axes[0].set_title("Trade count by product/day")
axes[0].tick_params(axis="x", rotation=90)

trade_qty = trades.groupby(["day", "symbol"])["quantity"].sum().reset_index(name="quantity")
sns.barplot(data=trade_qty, x="symbol", y="quantity", hue="day", ax=axes[1])
axes[1].set_title("Total traded quantity by product/day")
axes[1].tick_params(axis="x", rotation=90)
plt.tight_layout()
savefig("round4_trade_activity_by_product.png")
plt.show()
"""
    ),
    code(
        r"""
participants = sorted(set(trades["buyer"]) | set(trades["seller"]))

buyer_flow = trades.groupby(["buyer", "symbol"]).agg(
    buy_qty=("quantity", "sum"),
    buy_notional=("notional", "sum"),
    buy_trades=("quantity", "size"),
).reset_index().rename(columns={"buyer": "participant"})

seller_flow = trades.groupby(["seller", "symbol"]).agg(
    sell_qty=("quantity", "sum"),
    sell_notional=("notional", "sum"),
    sell_trades=("quantity", "size"),
).reset_index().rename(columns={"seller": "participant"})

flow = buyer_flow.merge(seller_flow, on=["participant", "symbol"], how="outer").fillna(0)
flow["net_qty"] = flow["buy_qty"] - flow["sell_qty"]
flow["gross_qty"] = flow["buy_qty"] + flow["sell_qty"]
flow["cashflow"] = flow["sell_notional"] - flow["buy_notional"]
flow["trades"] = flow["buy_trades"] + flow["sell_trades"]

top_flow = flow.groupby("participant").agg(
    gross_qty=("gross_qty", "sum"),
    net_abs_qty=("net_qty", lambda x: x.abs().sum()),
    trades=("trades", "sum"),
    products=("symbol", "nunique"),
).sort_values("gross_qty", ascending=False)

display(top_flow.head(20).round(2))

fig, ax = plt.subplots(figsize=(15, 8))
heat = flow.pivot_table(index="participant", columns="symbol", values="net_qty", aggfunc="sum", fill_value=0)
heat = heat.loc[heat.abs().sum(axis=1).sort_values(ascending=False).head(25).index, ALL_PRODUCTS]
sns.heatmap(heat, cmap="coolwarm", center=0, ax=ax)
ax.set_title("Top participants: net bought quantity by product")
plt.tight_layout()
savefig("round4_counterparty_net_qty_heatmap.png")
plt.show()
"""
    ),
    code(
        r"""
pair_flow = trades.groupby(["buyer", "seller"]).agg(
    trades=("quantity", "size"),
    qty=("quantity", "sum"),
    notional=("notional", "sum"),
).reset_index()

top_pairs = pair_flow.sort_values("qty", ascending=False).head(30)
display(top_pairs)

pair_matrix = pair_flow.pivot_table(index="buyer", columns="seller", values="qty", aggfunc="sum", fill_value=0)
top_ids = top_flow.head(20).index
pair_matrix = pair_matrix.reindex(index=top_ids, columns=top_ids).fillna(0)

fig, ax = plt.subplots(figsize=(14, 11))
sns.heatmap(pair_matrix, cmap="mako", ax=ax)
ax.set_title("Trade quantity from buyer to seller among top participants")
plt.tight_layout()
savefig("round4_buyer_seller_pair_matrix.png")
plt.show()
"""
    ),
    md("## Counterparty Markout Analysis"),
    code(
        r"""
trades_marked = add_future_mids_to_trades(trades, prices, horizons=(100, 500, 1000, 5000, 10000))

edge_rows = []
for h in [100, 500, 1000, 5000, 10000]:
    b = trades_marked.groupby(["buyer", "symbol"]).agg(
        edge=(f"buyer_edge_{h}", "mean"),
        edge_notional=(f"buyer_edge_notional_{h}", "sum"),
        qty=("quantity", "sum"),
        trades=("quantity", "size"),
    ).reset_index().rename(columns={"buyer": "participant"})
    b["side"] = "buyer"
    b["horizon"] = h

    s = trades_marked.groupby(["seller", "symbol"]).agg(
        edge=(f"seller_edge_{h}", "mean"),
        edge_notional=(f"seller_edge_notional_{h}", "sum"),
        qty=("quantity", "sum"),
        trades=("quantity", "size"),
    ).reset_index().rename(columns={"seller": "participant"})
    s["side"] = "seller"
    s["horizon"] = h
    edge_rows.append(pd.concat([b, s], ignore_index=True))

edges = pd.concat(edge_rows, ignore_index=True).dropna(subset=["edge"])
edges["edge_per_unit"] = edges["edge_notional"] / edges["qty"].replace(0, np.nan)

edge_summary_1000 = edges[(edges["horizon"] == 1000) & (edges["trades"] >= 5)].copy()
display(edge_summary_1000.sort_values("edge_per_unit", ascending=False).head(30).round(3))
display(edge_summary_1000.sort_values("edge_per_unit", ascending=True).head(30).round(3))

edges.to_csv(ANALYSED_DIR / "round4_counterparty_markout_edges.csv", index=False)
"""
    ),
    code(
        r"""
participant_edge = edges[(edges["horizon"] == 1000) & (edges["trades"] >= 10)].groupby(["participant", "side"]).agg(
    edge_per_unit=("edge_per_unit", "mean"),
    edge_notional=("edge_notional", "sum"),
    trades=("trades", "sum"),
    qty=("qty", "sum"),
).reset_index()

participant_edge["label"] = participant_edge["participant"] + " " + participant_edge["side"]
best = participant_edge.sort_values("edge_per_unit", ascending=False).head(20)
worst = participant_edge.sort_values("edge_per_unit", ascending=True).head(20)

fig, axes = plt.subplots(1, 2, figsize=(20, 8), sharex=False)
sns.barplot(data=best, y="label", x="edge_per_unit", ax=axes[0], palette="crest")
axes[0].axvline(0, color="black", linewidth=1)
axes[0].set_title("Best 1000-step markout by participant/side")
axes[0].set_xlabel("Future edge per unit")
axes[0].set_ylabel("")

sns.barplot(data=worst, y="label", x="edge_per_unit", ax=axes[1], palette="flare")
axes[1].axvline(0, color="black", linewidth=1)
axes[1].set_title("Worst 1000-step markout by participant/side")
axes[1].set_xlabel("Future edge per unit")
axes[1].set_ylabel("")
plt.tight_layout()
savefig("round4_counterparty_best_worst_markouts.png")
plt.show()
"""
    ),
    code(
        r"""
product_edge = edges[(edges["horizon"] == 1000) & (edges["trades"] >= 3)].copy()
product_edge["participant_side"] = product_edge["participant"] + " " + product_edge["side"]

ranked_ids = (
    product_edge.groupby("participant_side")["edge_notional"].sum()
    .abs()
    .sort_values(ascending=False)
    .head(25)
    .index
)

heat = product_edge[product_edge["participant_side"].isin(ranked_ids)].pivot_table(
    index="participant_side",
    columns="symbol",
    values="edge_per_unit",
    aggfunc="mean",
)
heat = heat.reindex(columns=ALL_PRODUCTS)

fig, ax = plt.subplots(figsize=(18, 10))
sns.heatmap(heat, cmap="coolwarm", center=0, annot=False, ax=ax)
ax.set_title("1000-step markout edge by participant side and product")
plt.tight_layout()
savefig("round4_counterparty_product_edge_heatmap.png")
plt.show()
"""
    ),
    code(
        r"""
focus_marks = top_flow.head(8).index.tolist()
fig, axes = plt.subplots(len(UNDERLYINGS), 1, figsize=(17, 10), sharex=True)
for ax, product in zip(axes, UNDERLYINGS):
    px = prices[prices["product"] == product]
    sns.lineplot(data=px, x="global_timestamp", y="mid_price", hue="day", palette="Greys", legend=False, linewidth=1, ax=ax)
    for mark in focus_marks:
        sub = trades[((trades["buyer"] == mark) | (trades["seller"] == mark)) & (trades["symbol"] == product)].copy()
        if sub.empty:
            continue
        sub["signed_qty"] = np.where(sub["buyer"] == mark, sub["quantity"], -sub["quantity"])
        ax.scatter(
            sub["global_timestamp"],
            sub["price"],
            s=np.clip(sub["quantity"] * 9, 15, 90),
            alpha=0.55,
            label=mark,
        )
    ax.set_title(f"{product}: top participant trades over price path")
    ax.set_ylabel("Price")
axes[-1].set_xlabel("Global timestamp")
handles, labels = axes[0].get_legend_handles_labels()
if handles:
    axes[0].legend(handles[:10], labels[:10], ncol=5, fontsize=9)
plt.tight_layout()
savefig("round4_top_marks_trade_overlays.png")
plt.show()
"""
    ),
    md(
        r"""
### Counterparty interpretation

The `edge_per_unit` metric is the cleanest first-pass signal:

- Buyer edge at horizon `h`: `future_mid - trade_price`
- Seller edge at horizon `h`: `trade_price - future_mid`

Positive values mean that participant/side was directionally right after the trade. A trader can use this in two ways:

1. Follow good counterparties: if a strong positive-edge buyer just bought, bias fair value upward or buy with them.
2. Fade weak counterparties: if a consistently negative-edge buyer just bought, treat the print as less informative or even contrarian.

This is not automatically a full strategy. It must be gated by product, horizon, and minimum sample size because some marks only trade a few times.
"""
    ),
    md("## Voucher Surface And Option Signals"),
    code(
        r"""
options = prices[prices["product"].isin(VOUCHERS)].copy()
underlying_mid = prices[prices["product"] == "VELVETFRUIT_EXTRACT"][["day", "timestamp", "mid_price"]].rename(columns={"mid_price": "S"})
options = options.merge(underlying_mid, on=["day", "timestamp"], how="left")
options["strike"] = options["product"].map(STRIKES).astype(int)
options["intrinsic"] = np.maximum(options["S"] - options["strike"], 0)
options["extrinsic"] = options["mid_price"] - options["intrinsic"]
options["moneyness"] = options["S"] / options["strike"]

chain_summary = options.groupby("product").agg(
    strike=("strike", "first"),
    mean_mid=("mid_price", "mean"),
    mean_intrinsic=("intrinsic", "mean"),
    mean_extrinsic=("extrinsic", "mean"),
    mean_spread=("spread", "mean"),
    mean_top_depth=("top_depth", "mean"),
    empty_rows=("book_empty", "sum"),
).sort_values("strike")
display(chain_summary.round(3))
"""
    ),
    code(
        r"""
fig, axes = plt.subplots(1, 2, figsize=(18, 6))
sns.lineplot(data=options, x="strike", y="mid_price", hue="day", estimator="mean", marker="o", ax=axes[0])
axes[0].set_title("Average voucher price by strike")
axes[0].set_ylabel("Average mid price")

sns.lineplot(data=options, x="strike", y="extrinsic", hue="day", estimator="mean", marker="o", ax=axes[1])
axes[1].axhline(0, color="black", linewidth=1)
axes[1].set_title("Average extrinsic value by strike")
axes[1].set_ylabel("Market mid minus intrinsic")
plt.tight_layout()
savefig("round4_voucher_price_and_extrinsic_by_strike.png")
plt.show()
"""
    ),
    code(
        r"""
snapshot_rows = []
for day in sorted(options["day"].unique()):
    ts_values = np.sort(options.loc[options["day"] == day, "timestamp"].unique())
    for ts in [ts_values[0], ts_values[len(ts_values)//2], ts_values[-1]]:
        chain = options[(options["day"] == day) & (options["timestamp"] == ts)].sort_values("strike")
        snapshot_rows.append(chain.assign(snapshot=f"day {day}, t={ts}"))
snapshots = pd.concat(snapshot_rows, ignore_index=True)

fig, axes = plt.subplots(1, 3, figsize=(21, 6), sharey=True)
for ax, day in zip(axes, sorted(options["day"].unique())):
    sub = snapshots[snapshots["day"] == day]
    sns.lineplot(data=sub, x="strike", y="mid_price", hue="snapshot", marker="o", ax=ax)
    sns.lineplot(data=sub, x="strike", y="intrinsic", hue="snapshot", marker="x", linestyle="--", ax=ax, legend=False)
    ax.set_title(f"Voucher chain snapshots, day {day}")
    ax.set_xlabel("Strike")
    ax.set_ylabel("Price")
plt.tight_layout()
savefig("round4_voucher_chain_snapshots.png")
plt.show()
"""
    ),
    code(
        r"""
arb_rows = []
for (day, ts), grp in options.groupby(["day", "timestamp"]):
    chain = grp.sort_values("strike")
    mids = chain["mid_price"].to_numpy()
    strikes = chain["strike"].to_numpy()
    monotone_violations = int(np.sum(np.diff(mids) > 1e-9))
    convex_violations = int(np.sum(np.diff(mids, n=2) < -1e-9))
    arb_rows.append(
        {
            "day": day,
            "timestamp": ts,
            "monotone_violations": monotone_violations,
            "convex_violations": convex_violations,
            "min_extrinsic": float(chain["extrinsic"].min()),
            "max_extrinsic": float(chain["extrinsic"].max()),
        }
    )
arb = pd.DataFrame(arb_rows)
display(arb.groupby("day")[["monotone_violations", "convex_violations", "min_extrinsic"]].agg(["mean", "max"]).round(4))

fig, axes = plt.subplots(1, 2, figsize=(17, 6))
sns.histplot(data=arb, x="monotone_violations", hue="day", multiple="dodge", shrink=0.8, ax=axes[0])
axes[0].set_title("Monotonicity violations per timestamp")
sns.histplot(data=arb, x="convex_violations", hue="day", multiple="dodge", shrink=0.8, ax=axes[1])
axes[1].set_title("Convexity violations per timestamp")
plt.tight_layout()
savefig("round4_voucher_static_arbitrage_checks.png")
plt.show()
"""
    ),
    code(
        r"""
fit_rows = []
for day in sorted(options["day"].unique()):
    ts_values = np.sort(options.loc[options["day"] == day, "timestamp"].unique())
    for ts in ts_values[::25]:
        chain = options[(options["day"] == day) & (options["timestamp"] == ts)].sort_values("strike").copy()
        S = float(chain["S"].iloc[0])
        strikes = chain["strike"].to_numpy(dtype=float)
        market = chain["mid_price"].to_numpy(dtype=float)
        sigma, model = best_fit_sigma(S, strikes, market, T=T_MAIN)
        for product, strike, market_price, model_price in zip(chain["product"], chain["strike"], market, model):
            fit_rows.append(
                {
                    "day": day,
                    "timestamp": ts,
                    "S": S,
                    "sigma": sigma,
                    "product": product,
                    "strike": int(strike),
                    "market_mid": float(market_price),
                    "model_price": float(model_price),
                    "residual": float(market_price - model_price),
                }
            )
fit_sample = pd.DataFrame(fit_rows)
display(fit_sample.groupby("day")["sigma"].agg(["mean", "std", "min", "max"]).round(4))
fit_sample.to_csv(ANALYSED_DIR / "round4_voucher_bs_fit_sample.csv", index=False)
"""
    ),
    code(
        r"""
fig, ax = plt.subplots(figsize=(16, 6))
sns.lineplot(data=fit_sample[["day", "timestamp", "sigma"]].drop_duplicates(), x="timestamp", y="sigma", hue="day", ax=ax)
ax.set_title("Sampled best-fit implied volatility through time")
ax.set_ylabel("Sigma")
plt.tight_layout()
savefig("round4_sampled_implied_vol.png")
plt.show()
"""
    ),
    code(
        r"""
residual_summary = fit_sample.groupby("product").agg(
    strike=("strike", "first"),
    mean_residual=("residual", "mean"),
    median_residual=("residual", "median"),
    std_residual=("residual", "std"),
    mean_market=("market_mid", "mean"),
    mean_model=("model_price", "mean"),
).sort_values("strike")

fig, ax = plt.subplots(figsize=(16, 6))
sns.barplot(data=residual_summary.reset_index(), x="product", y="mean_residual", palette="coolwarm", ax=ax)
ax.axhline(0, color="black", linewidth=1)
ax.set_title("Average voucher residual vs best-fit Black-Scholes surface")
ax.set_xlabel("Voucher")
ax.set_ylabel("Market mid - model price")
ax.tick_params(axis="x", rotation=45)
plt.tight_layout()
savefig("round4_voucher_model_residuals.png")
plt.show()

display(residual_summary.round(4))
"""
    ),
    code(
        r"""
resid_pivot = fit_sample.pivot_table(index="timestamp", columns="product", values="residual", aggfunc="mean")
resid_pivot = resid_pivot[VOUCHERS]
fig, ax = plt.subplots(figsize=(18, 8))
sns.heatmap(resid_pivot.T, cmap="coolwarm", center=0, ax=ax, cbar_kws={"label": "Residual"})
ax.set_title("Voucher residuals through time: market mid minus fitted model")
ax.set_xlabel("Sampled timestamp")
ax.set_ylabel("Voucher")
plt.tight_layout()
savefig("round4_voucher_residual_heatmap.png")
plt.show()
"""
    ),
    code(
        r"""
tte_sensitivity = []
for T_days in [2, 3, 4, 5, 6]:
    rows = []
    for day in sorted(options["day"].unique()):
        ts_values = np.sort(options.loc[options["day"] == day, "timestamp"].unique())
        for ts in ts_values[::100]:
            chain = options[(options["day"] == day) & (options["timestamp"] == ts)].sort_values("strike")
            sigma, model = best_fit_sigma(
                float(chain["S"].iloc[0]),
                chain["strike"].to_numpy(dtype=float),
                chain["mid_price"].to_numpy(dtype=float),
                T=T_days / 365,
            )
            rows.append({"T_days": T_days, "day": day, "timestamp": ts, "sigma": sigma, "rmse": float(np.sqrt(((model - chain["mid_price"].to_numpy()) ** 2).mean()))})
    tte_sensitivity.append(pd.DataFrame(rows))
tte_sensitivity = pd.concat(tte_sensitivity, ignore_index=True)

display(tte_sensitivity.groupby("T_days")[["sigma", "rmse"]].agg(["mean", "std"]).round(4))

fig, axes = plt.subplots(1, 2, figsize=(17, 6))
sns.boxplot(data=tte_sensitivity, x="T_days", y="sigma", ax=axes[0])
axes[0].set_title("Best-fit sigma sensitivity to TTE assumption")
sns.boxplot(data=tte_sensitivity, x="T_days", y="rmse", ax=axes[1])
axes[1].set_title("Model RMSE sensitivity to TTE assumption")
plt.tight_layout()
savefig("round4_tte_sensitivity.png")
plt.show()
"""
    ),
    md(
        r"""
### Voucher interpretation

The fitted surface is not meant to be a perfect options model. It is a compact way to detect cross-sectional mispricing. The most useful outputs are:

- stable or unstable fitted sigma through time,
- residuals by strike,
- residual heatmaps that show whether a voucher is persistently rich or cheap,
- static-arbitrage checks for monotonicity and convexity.

For implementation, do not overfit every residual. Prefer persistent, repeated residuals in liquid strikes or strikes with obvious model structure.
"""
    ),
    md("## Combined Signal Candidates"),
    code(
        r"""
# Build a lightweight table of candidate signals that could be implemented in trader.py.
signal_rows = []

for product in UNDERLYINGS:
    s = imbalance_summary.loc[product]
    ac1 = autocorr_df[(autocorr_df["product"] == product) & (autocorr_df["lag"] == 1)]["autocorr"].iloc[0]
    signal_rows.append(
        {
            "asset": product,
            "signal": "mean reversion + top-book imbalance",
            "evidence": f"lag1 autocorr={ac1:.3f}, imbalance corr={s['corr_imbalance_next_move']:.3f}",
            "implementation_hint": "skew fair value with imbalance; take stretched quotes around rolling/anchored fair",
            "risk": "inventory at empty-book or regime-change timestamps",
        }
    )

for product, row in residual_summary.iterrows():
    if abs(row["mean_residual"]) >= 2:
        side = "sell rich" if row["mean_residual"] > 0 else "buy cheap"
        signal_rows.append(
            {
                "asset": product,
                "signal": f"voucher residual: {side}",
                "evidence": f"mean residual={row['mean_residual']:.2f}, std={row['std_residual']:.2f}",
                "implementation_hint": "compare live voucher mid/bid/ask to fitted surface and trade only with edge buffer",
                "risk": "surface fit error, delta exposure to VELVETFRUIT_EXTRACT",
            }
        )

edge_candidates = edge_summary_1000[(edge_summary_1000["trades"] >= 5) & (edge_summary_1000["edge_per_unit"].abs() >= 1.0)].copy()
for _, row in edge_candidates.sort_values("edge_per_unit", key=lambda x: x.abs(), ascending=False).head(15).iterrows():
    direction = "follow" if row["edge_per_unit"] > 0 else "fade"
    signal_rows.append(
        {
            "asset": row["symbol"],
            "signal": f"{direction} {row['participant']} as {row['side']}",
            "evidence": f"1000-step edge/unit={row['edge_per_unit']:.2f}, trades={int(row['trades'])}",
            "implementation_hint": "adjust fair value for a few ticks after this participant-side appears in market_trades",
            "risk": "sample size and same-participant behavior may shift in final",
        }
    )

signal_table = pd.DataFrame(signal_rows)
display(signal_table)
signal_table.to_csv(ANALYSED_DIR / "round4_signal_candidates.csv", index=False)
"""
    ),
    code(
        r"""
fig, axes = plt.subplots(2, 2, figsize=(19, 13))

if not residual_summary.empty:
    sns.barplot(data=residual_summary.reset_index(), x="product", y="mean_residual", palette="coolwarm", ax=axes[0, 0])
    axes[0, 0].axhline(0, color="black", linewidth=1)
    axes[0, 0].set_title("Voucher residual ranking")
    axes[0, 0].tick_params(axis="x", rotation=90)

strong_edges = edge_summary_1000[edge_summary_1000["trades"] >= 5].copy()
strong_edges["label"] = strong_edges["participant"] + " " + strong_edges["side"] + " " + strong_edges["symbol"]
strong_edges = strong_edges.sort_values("edge_per_unit", key=lambda x: x.abs(), ascending=False).head(20)
sns.barplot(data=strong_edges, y="label", x="edge_per_unit", palette="vlag", ax=axes[0, 1])
axes[0, 1].axvline(0, color="black", linewidth=1)
axes[0, 1].set_title("Largest counterparty markout candidates")
axes[0, 1].set_ylabel("")

sns.lineplot(data=autocorr_df, x="lag", y="autocorr", hue="product", marker="o", ax=axes[1, 0])
axes[1, 0].axhline(0, color="black", linewidth=1)
axes[1, 0].set_title("Underlying mean-reversion diagnostic")

sns.barplot(data=trade_counts, x="symbol", y="trades", hue="day", ax=axes[1, 1])
axes[1, 1].set_title("Where trade prints exist")
axes[1, 1].tick_params(axis="x", rotation=90)

plt.tight_layout()
savefig("round4_signal_dashboard.png")
plt.show()
"""
    ),
    md(
        r"""
## Actionable Next Steps For `trader.py`

1. Keep the Round 3 baseline blocks for the two underlyings and the voucher surface model. Round 4 did not introduce new products; it introduced named counterparties.
2. Add a counterparty memory layer: store the last few `market_trades` by `participant`, `side`, `product`, and timestamp.
3. Use a small fair-value adjustment after strong participant-side prints. Start with only the top few high-sample, high-edge entries from `round4_counterparty_markout_edges.csv`.
4. Do not blindly follow every Mark. Gate by product and minimum historical count. A Mark can be good in one product and noise in another.
5. Treat vouchers through relative value, not raw price. Use `VELVETFRUIT_EXTRACT` as the state variable, fit a lightweight volatility/surface approximation, and trade only residuals with a buffer.
6. Keep risk controls tighter than Round 3 for vouchers. Counterparty signals can create clustered inventory; cap exposure per strike and avoid carrying large short gamma into the close.

The two files most directly useful for implementation are:

- `round_4/analysed/round4_counterparty_markout_edges.csv`
- `round_4/analysed/round4_signal_candidates.csv`
"""
    ),
]

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    },
    "language_info": {
        "name": "python",
        "pygments_lexer": "ipython3",
    },
}

nbf.write(nb, NOTEBOOK_PATH)
print(f"Wrote {NOTEBOOK_PATH}")
