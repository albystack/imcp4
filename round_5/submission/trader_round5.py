"""
IMC Prosperity Round 5 — Final Trader
=====================================

Strategy summary (derived from analysis of days 2-4):

A) **Strong mean-reverters (taker)** — high-confidence signal:
   • ROBOT_DISHES         : EWMA(α=0.5) fair, take when |best - fair| > 10
   • OXYGEN_SHAKE_EVENING_BREATH : EWMA(α=0.0005) fair, take when > 8

B) **PEBBLES basket invariant** (used as MM ANCHOR, not crossing arb):
   PEBBLES_XS+S+M+L+XL ≈ 50000 (std ≈ 2.8). Deviations are too small (~3 ticks)
   to overcome the per-leg spread (~12) when crossing — so we skip the taker
   variant. Instead we use the basket-implied shift to skew our market-making
   quotes (push bid up / ask up when basket says pebbles are cheap).

C) **SNACKPACK_CHOCOLATE + SNACKPACK_VANILLA pair-trade**:
   Their sum ≈ 19940 with slow daily drift. Track local target via slow EWMA,
   take both legs when sum is far from target.

D) **Wide-spread market making** on:
     - SNACKPACK family (5 products, spread ≈ 17)
     - OXYGEN_SHAKE_CHOCOLATE (proven 3/3 days positive)
     - TRANSLATOR_VOID_BLUE + TRANSLATOR_ECLIPSE_CHARCOAL (+21k incremental)
   Place limit orders inside BBO, skewing prices by inventory.
   Skip products that backtested negative or unstable (PEBBLES MM, UV_VISOR,
   GALAXY_SOUNDS as MM, MICROCHIPS, SLEEP_PODS, PANELS, other ROBOT_*).

E) Position limits: 10 per product (hard).
"""

from typing import Dict, List, Any
import json
import math

try:
    from datamodel import OrderDepth, TradingState, Order
except ImportError:
    # local stubs for static analysis
    class Order:
        def __init__(self, symbol, price, quantity):
            self.symbol = symbol; self.price = price; self.quantity = quantity
    class OrderDepth: pass
    class TradingState: pass


# ---------------------------------------------------------------------------
# Static product information
# ---------------------------------------------------------------------------

POSITION_LIMIT = 10

PEBBLES = ['PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL']
SNACKPACK = ['SNACKPACK_CHOCOLATE', 'SNACKPACK_VANILLA',
             'SNACKPACK_PISTACHIO', 'SNACKPACK_STRAWBERRY', 'SNACKPACK_RASPBERRY']

# Wide-spread products to market-make on. We restrict to the SNACKPACK family
# (spread ~17 ticks; very low daily drift) where the spread-vs-volatility ratio
# leaves clear edge after typical adverse selection. Other wide-spread products
# (GALAXY_SOUNDS, UV_VISOR, OXYGEN_SHAKE, PEBBLES) have smaller spreads relative
# to their per-tick volatility and were unprofitable in pessimistic backtests.
MM_PRODUCTS = {
    # SNACKPACK family — spread ≈ 17, very low daily drift.
    # Sizes raised (4→8 outer, 3→6 inner) because order books carry ~30 at BBO
    # and the prior backtest was leaving lots of flow uncaptured (only 250-400
    # fills/day per snackpack with size=3-4).
    'SNACKPACK_RASPBERRY':  {'edge': 2, 'mm_size': 8},
    'SNACKPACK_PISTACHIO':  {'edge': 2, 'mm_size': 8},
    'SNACKPACK_STRAWBERRY': {'edge': 2, 'mm_size': 8},
    # CHOCOLATE & VANILLA also do MM, but the pair-trade module owns inventory routing
    'SNACKPACK_CHOCOLATE':  {'edge': 2, 'mm_size': 6},
    'SNACKPACK_VANILLA':    {'edge': 2, 'mm_size': 6},

    # OXYGEN_SHAKE addition — only the consistently profitable one.
    # Backtest evidence on days 2-4 (with edge=3, mm_size=4):
    #   CHOCOLATE: D2 +9.1k  D3 +9.1k  D4 +2.4k = +20.6k   (3/3 positive ✅)
    # MORNING_BREATH was tested too (D2 -0.4k, D3 -8.8k, D4 +4.2k = -5k net)
    # so it's dropped. GARLIC and MINT also dropped.
    'OXYGEN_SHAKE_CHOCOLATE': {'edge': 3, 'mm_size': 4},

    # TRANSLATOR additions — VOID_BLUE & ECLIPSE_CHARCOAL only.
    # All 5 translators were tested as a group (-13k), but VOID_BLUE and
    # ECLIPSE_CHARCOAL alone are clear winners. Backtest evidence (edge=1, mm_size=3):
    #   VOID_BLUE:        D2 +5.8k  D3 -0.6k  D4 +7.8k = +13.0k
    #   ECLIPSE_CHARCOAL: D2 +2.7k  D3 -1.1k  D4 +6.5k = +8.1k
    #   Combined effect:  +21k incremental over baseline.
    # Edge=1 is the right level: their spread is tighter than snackpacks, and
    # raising to edge=2 gives up too much volume on D3 (-7k on ECLIPSE).
    # Other 3 translators (SPACE_GRAY, ASTRO_BLACK, GRAPHITE_MIST) are net
    # negative or flat across days — keep them out.
    'TRANSLATOR_VOID_BLUE':        {'edge': 1, 'mm_size': 3},
    'TRANSLATOR_ECLIPSE_CHARCOAL': {'edge': 1, 'mm_size': 3},
}

# EWMA-taker config: products where price reverts strongly toward a (slow- or
# fast-moving) local mean. Threshold is in price ticks above/below the EWMA fair
# at which to *cross the spread* and take liquidity.
# Tuning: chose params that maximize avg P&L while keeping worst-day drawdown
# small (risk-adjusted across days 2-4).
TAKER_CONFIG = {
    'ROBOT_DISHES':                {'alpha': 0.50,   'thr': 10},
    'OXYGEN_SHAKE_EVENING_BREATH': {'alpha': 0.0005, 'thr': 8},
}

# Pebble basket-arb threshold: take liquidity when the basket-anchored fair
# value of an individual pebble disagrees with the level-1 quote by ≥ 1 tick.
PEBBLES_TARGET = 50000
PEBBLES_THR = 1

# CHOC + VAN pair-trade
PAIR_PROD_A = 'SNACKPACK_CHOCOLATE'
PAIR_PROD_B = 'SNACKPACK_VANILLA'
PAIR_INIT_TARGET = 19940      # initial centroid (will adapt)
PAIR_ALPHA       = 0.0005     # slow EWMA so daily drift is tracked
PAIR_THR         = 70         # cross both spreads (~34) + buffer for drift


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def best_bid_ask(depth: OrderDepth):
    """Return (best_bid, best_bid_vol, best_ask, best_ask_vol) or Nones."""
    best_bid = best_ask = None
    bid_vol = ask_vol = 0
    if depth.buy_orders:
        best_bid = max(depth.buy_orders.keys())
        bid_vol = depth.buy_orders[best_bid]            # positive
    if depth.sell_orders:
        best_ask = min(depth.sell_orders.keys())
        ask_vol = -depth.sell_orders[best_ask]          # convert to positive
    return best_bid, bid_vol, best_ask, ask_vol


def mid_of(depth: OrderDepth):
    bb, _, ba, _ = best_bid_ask(depth)
    if bb is None or ba is None:
        return None
    return (bb + ba) / 2.0


def clamp_qty(want: int, position: int, limit: int = POSITION_LIMIT) -> int:
    """Clamp `want` (signed) so resulting position stays in [-limit, +limit]."""
    if want > 0:
        return max(0, min(want, limit - position))
    elif want < 0:
        return min(0, max(want, -limit - position))
    return 0


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------

class Trader:
    def run(self, state: TradingState):
        # --------------------------------------------------------------
        # Load persistent state
        # --------------------------------------------------------------
        try:
            mem = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            mem = {}

        fair_ewma = mem.get('fair_ewma', {})
        pair_target = mem.get('pair_target', PAIR_INIT_TARGET)

        result: Dict[str, List[Order]] = {}
        positions = state.position if hasattr(state, 'position') else {}

        # --------------------------------------------------------------
        # 0) Snapshot mids for cross-product strategies (pebbles, pairs)
        # --------------------------------------------------------------
        mids: Dict[str, float] = {}
        for prod, depth in state.order_depths.items():
            m = mid_of(depth)
            if m is not None:
                mids[prod] = m

        # --------------------------------------------------------------
        # 1) Strong-mean-revert TAKER (ROBOT_DISHES, OXYGEN_SHAKE_EVENING_BREATH)
        # --------------------------------------------------------------
        for prod, cfg in TAKER_CONFIG.items():
            depth = state.order_depths.get(prod)
            if depth is None:
                continue
            m = mids.get(prod)
            if m is None:
                continue

            fair = fair_ewma.get(prod, m)
            fair = (1 - cfg['alpha']) * fair + cfg['alpha'] * m
            fair_ewma[prod] = fair

            pos = positions.get(prod, 0)
            orders: List[Order] = []
            bb, bbv, ba, bav = best_bid_ask(depth)
            thr = cfg['thr']

            # Take ask (buy) if it's well below fair
            if ba is not None and ba < fair - thr and pos < POSITION_LIMIT:
                qty = min(POSITION_LIMIT - pos, bav)
                if qty > 0:
                    orders.append(Order(prod, ba, qty))
            # Take bid (sell) if it's well above fair
            if bb is not None and bb > fair + thr and pos > -POSITION_LIMIT:
                qty = min(POSITION_LIMIT + pos, bbv)
                if qty > 0:
                    orders.append(Order(prod, bb, -qty))

            if orders:
                result[prod] = orders

        # --------------------------------------------------------------
        # 2) PEBBLES basket-implied shift  (informs MM only, no crossing)
        #    Each pebble's true fair = mid_i + (50000 - sum) / 5
        #    The deviation is too small (~3 ticks) to profitably cross the
        #    ~12-tick spread, so we just record the per-pebble shift and let
        #    the MM block use it to skew its quotes.
        # --------------------------------------------------------------
        pebble_shift = 0.0
        if all(p in mids for p in PEBBLES):
            sum_mid = sum(mids[p] for p in PEBBLES)
            pebble_shift = (PEBBLES_TARGET - sum_mid) / 5.0

        # --------------------------------------------------------------
        # 3) CHOC + VAN pair-trade with adaptive local target
        # --------------------------------------------------------------
        if PAIR_PROD_A in mids and PAIR_PROD_B in mids:
            m_a = mids[PAIR_PROD_A]; m_b = mids[PAIR_PROD_B]
            sum_pair = m_a + m_b
            pair_target = (1 - PAIR_ALPHA) * pair_target + PAIR_ALPHA * sum_pair
            dev = sum_pair - pair_target

            depth_a = state.order_depths[PAIR_PROD_A]
            depth_b = state.order_depths[PAIR_PROD_B]
            pos_a = positions.get(PAIR_PROD_A, 0)
            pos_b = positions.get(PAIR_PROD_B, 0)
            bb_a, bbv_a, ba_a, bav_a = best_bid_ask(depth_a)
            bb_b, bbv_b, ba_b, bav_b = best_bid_ask(depth_b)
            orders_a = result.get(PAIR_PROD_A, [])
            orders_b = result.get(PAIR_PROD_B, [])

            if dev > PAIR_THR:
                # Sum too high → SELL both
                if bb_a is not None and pos_a > -POSITION_LIMIT:
                    qty = min(POSITION_LIMIT + pos_a, bbv_a)
                    if qty > 0:
                        orders_a.append(Order(PAIR_PROD_A, bb_a, -qty))
                        pos_a -= qty
                if bb_b is not None and pos_b > -POSITION_LIMIT:
                    qty = min(POSITION_LIMIT + pos_b, bbv_b)
                    if qty > 0:
                        orders_b.append(Order(PAIR_PROD_B, bb_b, -qty))
                        pos_b -= qty
            elif dev < -PAIR_THR:
                # Sum too low → BUY both
                if ba_a is not None and pos_a < POSITION_LIMIT:
                    qty = min(POSITION_LIMIT - pos_a, bav_a)
                    if qty > 0:
                        orders_a.append(Order(PAIR_PROD_A, ba_a, qty))
                        pos_a += qty
                if ba_b is not None and pos_b < POSITION_LIMIT:
                    qty = min(POSITION_LIMIT - pos_b, bav_b)
                    if qty > 0:
                        orders_b.append(Order(PAIR_PROD_B, ba_b, qty))
                        pos_b += qty
            if orders_a:
                result[PAIR_PROD_A] = orders_a
            if orders_b:
                result[PAIR_PROD_B] = orders_b

        # --------------------------------------------------------------
        # 4) Wide-spread MARKET MAKING on selected products
        #    Place limit orders just inside BBO with inventory skew.
        # --------------------------------------------------------------
        for prod, cfg in MM_PRODUCTS.items():
            depth = state.order_depths.get(prod)
            if depth is None:
                continue
            bb, bbv, ba, bav = best_bid_ask(depth)
            if bb is None or ba is None:
                continue
            spread = ba - bb
            # need at least 2*edge + 1 tick gap to avoid crossing/joining
            if spread < 2 * cfg['edge'] + 1:
                continue

            mid = (bb + ba) / 2.0
            pos = positions.get(prod, 0)
            # Inventory skew: when long, lower both quotes; when short, raise them
            skew = -pos / POSITION_LIMIT * 2.0          # ±2 tick max skew
            # Pebble basket shift: if shift > 0 (basket says pebbles are cheap),
            # raise both quotes so we end up net long pebbles overall
            if prod in PEBBLES:
                skew += pebble_shift                   # at most ±~3 ticks
            my_bid = int(math.floor(bb + cfg['edge'] + skew))
            my_ask = int(math.ceil (ba - cfg['edge'] + skew))
            # Sanity: keep my_bid < my_ask (no self-cross)
            if my_bid >= my_ask:
                my_bid = my_ask - 1
            # Don't post a bid above existing best ask or ask below existing best bid
            if my_bid >= ba: my_bid = ba - 1
            if my_ask <= bb: my_ask = bb + 1

            size = cfg['mm_size']
            buy_qty  = clamp_qty( size, pos)
            sell_qty = clamp_qty(-size, pos)

            existing = result.get(prod, [])
            if buy_qty  > 0:
                existing.append(Order(prod, my_bid,  buy_qty))
            if sell_qty < 0:
                existing.append(Order(prod, my_ask, sell_qty))
            if existing:
                result[prod] = existing

        # --------------------------------------------------------------
        # 5) Persist state
        # --------------------------------------------------------------
        mem['fair_ewma']   = fair_ewma
        mem['pair_target'] = pair_target
        traderData = json.dumps(mem)

        return result, 0, traderData
