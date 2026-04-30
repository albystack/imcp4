class Logger:
    def __init__(self):
        self.logs = ""
        self.max_log_length = 2500

    def print(self, *objects, sep=" ", end="\n"):
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state, orders, conversions, trader_data):
        json_module = self._json_module(state)
        base_length = len(
            self.to_json(
                json_module,
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ],
            )
        )
        max_item_length = max(0, (self.max_log_length - base_length) // 3)

        print(
            self.to_json(
                json_module,
                [
                    self.compress_state(state, self.truncate(json_module, state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(json_module, trader_data, max_item_length),
                    self.truncate(json_module, self.logs, max_item_length),
                ],
            )
        )
        self.logs = ""

    def _json_module(self, state):
        return state.__class__.toJSON.__globals__["json"]

    def compress_state(self, state, trader_data):
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings):
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(self, order_depths):
        compressed = {}
        for symbol, depth in order_depths.items():
            compressed[symbol] = [depth.buy_orders, depth.sell_orders]
        return compressed

    def compress_trades(self, trades):
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append([trade.symbol, trade.price, trade.quantity, trade.buyer, trade.seller, trade.timestamp])
        return compressed

    def compress_observations(self, observations):
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                getattr(observation, "sugarPrice", 0),
                getattr(observation, "sunlightIndex", 0),
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders):
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, json_module, value):
        return json_module.dumps(value, separators=(",", ":"))

    def truncate(self, json_module, value, max_length):
        if max_length <= 0:
            return ""

        lo = 0
        hi = min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            if len(json_module.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


class Trader:
    UNDERLYINGS = ("HYDROGEL_PACK", "VELVETFRUIT_EXTRACT")
    VOUCHERS = (
        "VEV_4000",
        "VEV_4500",
        "VEV_5000",
        "VEV_5100",
        "VEV_5200",
        "VEV_5300",
        "VEV_5400",
        "VEV_5500",
        "VEV_6000",
        "VEV_6500",
    )
    TRADE_VOUCHERS = (
        "VEV_4000",
        "VEV_4500",
        "VEV_5000",
        "VEV_5200",
        "VEV_5300",
        "VEV_5500",
        "VEV_6000",
        "VEV_6500",
    )
    STRIKES = {
        "VEV_4000": 4000,
        "VEV_4500": 4500,
        "VEV_5000": 5000,
        "VEV_5100": 5100,
        "VEV_5200": 5200,
        "VEV_5300": 5300,
        "VEV_5400": 5400,
        "VEV_5500": 5500,
        "VEV_6000": 6000,
        "VEV_6500": 6500,
    }
    ACTIVE_LIMITS = {
        "HYDROGEL_PACK": 120,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 90,
        "VEV_4500": 90,
        "VEV_5000": 90,
        "VEV_5100": 90,
        "VEV_5200": 90,
        "VEV_5300": 90,
        "VEV_5400": 90,
        "VEV_5500": 90,
        "VEV_6000": 90,
        "VEV_6500": 90,
    }
    EMA_ALPHA = {
        "HYDROGEL_PACK": 0.08,
        "VELVETFRUIT_EXTRACT": 0.10,
    }

    def run(self, state):
        self.Order = state.__class__.toJSON.__globals__["Order"]
        memory = self._decode_memory(state.traderData)
        mids = self._collect_mids(state)
        self._update_emas(memory, mids)

        result = {}
        for product in state.order_depths:
            result[product] = []

        for product in self.UNDERLYINGS:
            if product in state.order_depths:
                result[product].extend(self._trade_underlying(product, state, memory))

        option_fairs, option_deltas, fit_sigma = self._option_fair_values(state)
        if option_fairs:
            for product in self.TRADE_VOUCHERS:
                if product in state.order_depths and product in option_fairs:
                    result[product].extend(self._trade_voucher(product, state, option_fairs[product], option_deltas[product]))

        if fit_sigma is not None:
            memory["sig"] = round(fit_sigma, 4)
        trader_data = self._encode_memory(memory)
        logger.print("ts", state.timestamp, "sig", memory.get("sig", ""))
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data

    def _decode_memory(self, trader_data):
        memory = {"ema": {}}
        if not trader_data:
            return memory
        for part in trader_data.split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            try:
                number = float(value)
            except Exception:
                continue
            if key == "HP":
                memory["ema"]["HYDROGEL_PACK"] = number
            elif key == "VE":
                memory["ema"]["VELVETFRUIT_EXTRACT"] = number
            elif key == "SIG":
                memory["sig"] = number
        return memory

    def _encode_memory(self, memory):
        ema = memory.get("ema", {})
        parts = []
        if "HYDROGEL_PACK" in ema:
            parts.append("HP=" + str(round(ema["HYDROGEL_PACK"], 4)))
        if "VELVETFRUIT_EXTRACT" in ema:
            parts.append("VE=" + str(round(ema["VELVETFRUIT_EXTRACT"], 4)))
        if "sig" in memory and memory["sig"] is not None:
            parts.append("SIG=" + str(round(memory["sig"], 4)))
        return ";".join(parts)

    def _collect_mids(self, state):
        mids = {}
        for product, depth in state.order_depths.items():
            mid = self._mid_price(depth)
            if mid is not None:
                mids[product] = mid
        return mids

    def _update_emas(self, memory, mids):
        ema = memory["ema"]
        for product in self.UNDERLYINGS:
            if product not in mids:
                continue
            alpha = self.EMA_ALPHA[product]
            previous = ema.get(product, mids[product])
            ema[product] = previous * (1.0 - alpha) + mids[product] * alpha

    def _best_bid_ask(self, depth):
        best_bid = max(depth.buy_orders) if depth.buy_orders else None
        best_ask = min(depth.sell_orders) if depth.sell_orders else None
        return best_bid, best_ask

    def _mid_price(self, depth):
        best_bid, best_ask = self._best_bid_ask(depth)
        if best_bid is None and best_ask is None:
            return None
        if best_bid is None:
            return float(best_ask)
        if best_ask is None:
            return float(best_bid)
        return (best_bid + best_ask) / 2.0

    def _imbalance(self, depth):
        best_bid, best_ask = self._best_bid_ask(depth)
        if best_bid is None or best_ask is None:
            return 0.0
        bid_volume = depth.buy_orders.get(best_bid, 0)
        ask_volume = abs(depth.sell_orders.get(best_ask, 0))
        denom = bid_volume + ask_volume
        if denom <= 0:
            return 0.0
        return (bid_volume - ask_volume) / denom

    def _position(self, state, product):
        return state.position.get(product, 0)

    def _buy_capacity(self, state, product, projected_position=None):
        position = self._position(state, product) if projected_position is None else projected_position
        return max(0, self.ACTIVE_LIMITS[product] - position)

    def _sell_capacity(self, state, product, projected_position=None):
        position = self._position(state, product) if projected_position is None else projected_position
        return max(0, self.ACTIVE_LIMITS[product] + position)

    def _trade_underlying(self, product, state, memory):
        depth = state.order_depths[product]
        best_bid, best_ask = self._best_bid_ask(depth)
        mid = self._mid_price(depth)
        if best_bid is None or best_ask is None or mid is None:
            return []

        ema = memory.get("ema", {}).get(product, mid)
        imbalance = self._imbalance(depth)
        if product == "HYDROGEL_PACK":
            fair = ema + 2.0 * imbalance
            take_edge = 9.0
            make_edge = 7.0
            base_size = 10
        else:
            fair = ema + 0.9 * imbalance
            take_edge = 3.0
            make_edge = 2.0
            base_size = 20

        orders = []
        projected_position = self._position(state, product)

        if best_ask <= fair - take_edge:
            qty = min(abs(depth.sell_orders[best_ask]), self._buy_capacity(state, product, projected_position), base_size * 2)
            if qty > 0:
                orders.append(self.Order(product, best_ask, qty))
                projected_position += qty

        if best_bid >= fair + take_edge:
            qty = min(depth.buy_orders[best_bid], self._sell_capacity(state, product, projected_position), base_size * 2)
            if qty > 0:
                orders.append(self.Order(product, best_bid, -qty))
                projected_position -= qty

        buy_quote = min(best_bid + 1, int(fair - make_edge))
        sell_quote = max(best_ask - 1, self._ceil(fair + make_edge))
        if buy_quote < sell_quote:
            skew = projected_position / self.ACTIVE_LIMITS[product]
            buy_size = int(base_size * max(0.25, 1.0 - max(0.0, skew)))
            sell_size = int(base_size * max(0.25, 1.0 + min(0.0, skew)))
            buy_size = min(buy_size, self._buy_capacity(state, product, projected_position))
            sell_size = min(sell_size, self._sell_capacity(state, product, projected_position))
            if buy_size > 0:
                orders.append(self.Order(product, int(buy_quote), buy_size))
            if sell_size > 0:
                orders.append(self.Order(product, int(sell_quote), -sell_size))

        return orders

    def _option_fair_values(self, state):
        underlying_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if underlying_depth is None:
            return {}, {}, None
        spot = self._mid_price(underlying_depth)
        if spot is None or spot <= 0:
            return {}, {}, None

        tte = 5.0 / 365.0
        points = []
        market = {}
        for product in self.VOUCHERS:
            depth = state.order_depths.get(product)
            if depth is None:
                continue
            mid = self._mid_price(depth)
            if mid is None:
                continue
            strike = self.STRIKES[product]
            iv = self._implied_volatility(mid, spot, strike, tte)
            if iv is None:
                continue
            moneyness = self._log(strike / spot) / (tte ** 0.5)
            market[product] = mid
            if product not in ("VEV_4000", "VEV_4500", "VEV_6500"):
                points.append((moneyness, iv, self._fit_weight(product)))

        if len(points) < 3:
            return {}, {}, None

        coeffs = self._quadratic_fit(points)
        if coeffs is None:
            return {}, {}, None

        fairs = {}
        deltas = {}
        fitted_sigmas = []
        for product in market:
            strike = self.STRIKES[product]
            moneyness = self._log(strike / spot) / (tte ** 0.5)
            fair_iv = self._eval_quadratic(coeffs, moneyness)
            fair_iv = min(1.0, max(0.02, fair_iv))
            fairs[product] = self._black_scholes_call(spot, strike, tte, fair_iv)
            deltas[product] = self._black_scholes_delta(spot, strike, tte, fair_iv)
            fitted_sigmas.append(fair_iv)

        fit_sigma = sum(fitted_sigmas) / len(fitted_sigmas) if fitted_sigmas else None
        return fairs, deltas, fit_sigma

    def _fit_weight(self, product):
        if product in ("VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"):
            return 2.0
        if product in ("VEV_5000", "VEV_6000"):
            return 1.0
        return 0.5

    def _black_scholes_call(self, spot, strike, tte, vol):
        if tte <= 0 or vol <= 0:
            return max(spot - strike, 0.0)
        d1 = (self._log(spot / strike) + 0.5 * vol * vol * tte) / (vol * (tte ** 0.5))
        d2 = d1 - vol * (tte ** 0.5)
        return spot * self._normal_cdf(d1) - strike * self._normal_cdf(d2)

    def _black_scholes_delta(self, spot, strike, tte, vol):
        if tte <= 0 or vol <= 0:
            return 1.0 if spot > strike else 0.0
        d1 = (self._log(spot / strike) + 0.5 * vol * vol * tte) / (vol * (tte ** 0.5))
        return self._normal_cdf(d1)

    def _implied_volatility(self, call_price, spot, strike, tte):
        intrinsic = max(spot - strike, 0.0)
        if call_price < intrinsic - 0.000001:
            return None

        low = 0.001
        high = 1.5
        low_price = self._black_scholes_call(spot, strike, tte, low)
        high_price = self._black_scholes_call(spot, strike, tte, high)
        if call_price <= low_price:
            return low
        if call_price >= high_price:
            return high

        for _ in range(50):
            mid = (low + high) / 2.0
            price = self._black_scholes_call(spot, strike, tte, mid)
            if price > call_price:
                high = mid
            else:
                low = mid
        return (low + high) / 2.0

    def _quadratic_fit(self, points):
        sums = [[0.0, 0.0, 0.0] for _ in range(3)]
        rhs = [0.0, 0.0, 0.0]
        for x, y, weight in points:
            row = [x * x, x, 1.0]
            for i in range(3):
                rhs[i] += weight * row[i] * y
                for j in range(3):
                    sums[i][j] += weight * row[i] * row[j]
        return self._solve_3x3(sums, rhs)

    def _solve_3x3(self, matrix, rhs):
        a = [matrix[i][:] + [rhs[i]] for i in range(3)]
        for col in range(3):
            pivot = max(range(col, 3), key=lambda row: abs(a[row][col]))
            if abs(a[pivot][col]) < 0.000000000001:
                return None
            a[col], a[pivot] = a[pivot], a[col]
            pivot_value = a[col][col]
            for j in range(col, 4):
                a[col][j] /= pivot_value
            for row in range(3):
                if row == col:
                    continue
                factor = a[row][col]
                for j in range(col, 4):
                    a[row][j] -= factor * a[col][j]
        return a[0][3], a[1][3], a[2][3]

    def _eval_quadratic(self, coeffs, x):
        a, b, c = coeffs
        return a * x * x + b * x + c

    def _trade_voucher(self, product, state, fair, delta):
        depth = state.order_depths[product]
        best_bid, best_ask = self._best_bid_ask(depth)
        if best_bid is None or best_ask is None:
            return []

        spread = best_ask - best_bid
        position = self._position(state, product)
        projected_position = position
        orders = []

        edge = max(1.0, min(6.0, 0.45 * spread))
        max_take = 18 if product in ("VEV_5300", "VEV_5400", "VEV_5500") else 12
        adjusted_fair = fair - 1.0 * delta * projected_position / max(1, self.ACTIVE_LIMITS[product])

        if best_ask < adjusted_fair - edge:
            qty = min(abs(depth.sell_orders[best_ask]), self._buy_capacity(state, product, projected_position), max_take)
            if qty > 0:
                orders.append(self.Order(product, best_ask, qty))
                projected_position += qty

        if best_bid > adjusted_fair + edge:
            qty = min(depth.buy_orders[best_bid], self._sell_capacity(state, product, projected_position), max_take)
            if qty > 0:
                orders.append(self.Order(product, best_bid, -qty))
                projected_position -= qty

        make_edge = max(1.0, min(5.0, 0.35 * spread))
        buy_quote = min(best_bid + 1, int(adjusted_fair - make_edge))
        sell_quote = max(best_ask - 1, self._ceil(adjusted_fair + make_edge))
        if buy_quote < sell_quote:
            base_size = 10 if product in ("VEV_5300", "VEV_5400", "VEV_5500") else 6
            skew = projected_position / self.ACTIVE_LIMITS[product]
            buy_size = int(base_size * max(0.2, 1.0 - max(0.0, skew)))
            sell_size = int(base_size * max(0.2, 1.0 + min(0.0, skew)))
            buy_size = min(buy_size, self._buy_capacity(state, product, projected_position))
            sell_size = min(sell_size, self._sell_capacity(state, product, projected_position))
            if buy_size > 0 and buy_quote >= 0:
                orders.append(self.Order(product, int(buy_quote), buy_size))
            if sell_size > 0:
                orders.append(self.Order(product, int(sell_quote), -sell_size))

        return orders

    def _ceil(self, value):
        integer = int(value)
        if value > integer:
            return integer + 1
        return integer

    def _log(self, x):
        if x <= 0:
            return -1000000000.0
        y = (x - 1.0) / (x + 1.0)
        y2 = y * y
        term = y
        total = 0.0
        denom = 1.0
        for _ in range(30):
            total += term / denom
            term *= y2
            denom += 2.0
        return 2.0 * total

    def _exp(self, x):
        if x < -60:
            return 0.0
        if x > 60:
            return 100000000000000000000000000.0
        return 2.718281828459045 ** x

    def _normal_cdf(self, x):
        if x > 8.0:
            return 1.0
        if x < -8.0:
            return 0.0
        z = abs(x)
        t = 1.0 / (1.0 + 0.2316419 * z)
        poly = t * (
            0.319381530
            + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429)))
        )
        pdf = 0.3989422804014327 * self._exp(-0.5 * z * z)
        cdf = 1.0 - pdf * poly
        if x < 0:
            return 1.0 - cdf
        return cdf
