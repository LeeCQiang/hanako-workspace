#!/usr/bin/env python3
"""
Hanako Trading System - Backtesting Engine
回测框架：验证多种策略在历史数据上的表现
"""
import json
import sys
import math
from datetime import datetime, timezone

# ============ 数据加载 ============

def load_klines(filepath, limit=None):
    with open(filepath) as f:
        raw = json.load(f)
    if limit:
        raw = raw[-limit:]
    data = []
    for k in raw:
        ts_ms = k[0]
        data.append({
            "time": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5])
        })
    return data

# ============ 技术指标 ============

def calc_sma(data, period):
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            avg = sum(d["close"] for d in data[i-period+1:i+1]) / period
            result.append(avg)
    return result

def calc_ema(data, period):
    result = []
    multiplier = 2 / (period + 1)
    for i in range(len(data)):
        if i == 0:
            result.append(data[i]["close"])
        elif i < period - 1:
            result.append(data[i]["close"])
        else:
            ema = (data[i]["close"] - result[i-1]) * multiplier + result[i-1]
            result.append(ema)
    return result

def calc_rsi(data, period=14):
    result = [None]
    gains = [0]
    losses = [0]
    for i in range(1, len(data)):
        diff = data[i]["close"] - data[i-1]["close"]
        g = max(diff, 0)
        l = max(-diff, 0)
        gains.append(g)
        losses.append(l)
        if i < period:
            result.append(None)
        elif i == period:
            avg_gain = sum(gains[1:period+1]) / period
            avg_loss = sum(losses[1:period+1]) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 999
            result.append(100 - 100 / (1 + rs))
        else:
            avg_gain = (result[i-1] if result[i-1] else 50)
            avg_gain = (gains[i-1] * (period - 1) + g) / period
            avg_loss = (losses[i-1] * (period - 1) + l) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 999
            result.append(100 - 100 / (1 + rs))
    return result

def calc_macd(data, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(data, fast)
    ema_slow = calc_ema(data, slow)
    macd_line = [ema_fast[i] - ema_slow[i] if ema_fast[i] and ema_slow[i] else None for i in range(len(data))]
    signal_line = []
    multiplier = 2 / (signal + 1)
    count = 0
    for i in range(len(data)):
        if macd_line[i] is None:
            signal_line.append(None)
            count = 0
        elif count < signal:
            signal_line.append(macd_line[i])
            count += 1
        else:
            sig = (macd_line[i] - signal_line[i-1]) * multiplier + signal_line[i-1]
            signal_line.append(sig)
    histogram = [macd_line[i] - signal_line[i] if macd_line[i] and signal_line[i] else None for i in range(len(data))]
    return macd_line, signal_line, histogram

def calc_atr(data, period=14):
    result = [None]
    for i in range(1, len(data)):
        high = data[i]["high"]
        low = data[i]["low"]
        prev_close = data[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        if i < period:
            result.append(tr)
        elif i == period:
            atr = sum(tr for tr in result[1:period+1]) / period
            result.append(atr)
        else:
            atr = (result[i-1] * (period - 1) + tr) / period
            result.append(atr)
    return result

# ============ 策略 ============

class Strategy:
    def __init__(self, name):
        self.name = name
        self.trades = []
        self.in_position = False
        self.entry_price = 0
        self.entry_idx = 0
    def on_bar(self, i, data, ind):
        raise NotImplementedError
    def buy(self, i, price, reason=""):
        self.in_position = True
        self.entry_price = price
        self.entry_idx = i
    def sell(self, i, price, reason=""):
        if self.in_position:
            pnl_pct = (price - self.entry_price) / self.entry_price * 100
            self.trades.append({
                "entry_idx": self.entry_idx, "exit_idx": i,
                "entry_price": round(self.entry_price, 2),
                "exit_price": round(price, 2),
                "pnl_pct": round(pnl_pct, 2), "reason": reason
            })
            self.in_position = False

class EMACrossover(Strategy):
    def __init__(self, fast=9, slow=21):
        super().__init__(f"EMA{fast}_{slow}_Cross")
        self.fast = fast
        self.slow = slow
    def on_bar(self, i, data, ind):
        ef, es = ind["ema_fast"][i], ind["ema_slow"][i]
        efp = ind["ema_fast"][i-1] if i > 0 else None
        esp = ind["ema_slow"][i-1] if i > 0 else None
        if None in (ef, es, efp, esp): return
        p = data[i]["close"]
        if not self.in_position and efp <= esp and ef > es:
            self.buy(i, p, f"金叉")
        if self.in_position and efp >= esp and ef < es:
            self.sell(i, p, f"死叉")

class EMARSICombo(Strategy):
    def __init__(self, ema_period=21, rsi_entry=38, rsi_exit=50):
        super().__init__(f"EMA{ema_period}_RSI{rsi_entry}")
        self.ema_p = ema_period
        self.rsi_entry = rsi_entry
        self.rsi_exit = rsi_exit
    def on_bar(self, i, data, ind):
        ema = ind["ema_slow"][i]
        rsi = ind["rsi"][i]
        p = data[i]["close"]
        if ema is None or rsi is None: return
        if not self.in_position and p > ema and rsi < self.rsi_entry:
            self.buy(i, p, f"RSI={rsi:.0f} EMA上方")
        if self.in_position:
            if rsi > self.rsi_exit:
                self.sell(i, p, f"RSI={rsi:.0f} 回归")
            elif p < ema * 0.97:
                self.sell(i, p, "破EMA")

class ATRTrendFollow(Strategy):
    def __init__(self, ema=21, atr_mult=2.0):
        super().__init__(f"ATRTrend_{ema}_{atr_mult}")
        self.ema_p = ema
        self.atr_m = atr_mult
        self.sl = 0
    def on_bar(self, i, data, ind):
        ema = ind["ema_slow"][i]
        atr = ind["atr"][i]
        p = data[i]["close"]
        if ema is None or atr is None: return
        if not self.in_position and p > ema and p > ema * 1.01:
            self.buy(i, p, f"趋势确认 ATR={atr:.0f}")
            self.sl = p - atr * self.atr_m
        if self.in_position:
            ns = p - atr * self.atr_m
            if ns > self.sl: self.sl = ns
            if p < self.sl:
                self.sell(i, p, f"追踪止损")
            elif p < ema * 0.98:
                self.sell(i, p, "破EMA")

class MACDStrategy(Strategy):
    def __init__(self):
        super().__init__("MACD_Cross")
    def on_bar(self, i, data, ind):
        m, s = ind["macd"][i], ind["macd_signal"][i]
        mp = ind["macd"][i-1] if i > 0 else None
        sp = ind["macd_signal"][i-1] if i > 0 else None
        if None in (m, s, mp, sp): return
        p = data[i]["close"]
        if not self.in_position and mp <= sp and m > s:
            self.buy(i, p, "MACD金叉")
        if self.in_position and mp >= sp and m < s:
            self.sell(i, p, "MACD死叉")

class BuyHold(Strategy):
    def __init__(self):
        super().__init__("BuyAndHold")
    def on_bar(self, i, data, ind):
        if not self.in_position:
            self.buy(i, data[i]["close"], "买入持有")

# ============ 回测引擎 ============

def run_backtest(data, strategies, capital=100000):
    ind = {
        "ema_fast": calc_ema(data, 9),
        "ema_slow": calc_sma(data, 21),
        "rsi": calc_rsi(data, 14),
        "atr": calc_atr(data, 14)
    }
    ind["macd"], ind["macd_signal"], _ = calc_macd(data)
    
    results = {}
    for strategy in strategies:
        s = strategy()
        for i in range(len(data)):
            s.on_bar(i, data, ind)
        if s.in_position:
            s.sell(len(data)-1, data[-1]["close"], "结账")
        
        trades = s.trades
        if not trades:
            results[s.name] = {"error": "无交易"}
            continue
        
        pnl = [t["pnl_pct"] for t in trades]
        wins = [x for x in pnl if x > 0]
        losses = [x for x in pnl if x <= 0]
        curve = [capital]
        for t in trades:
            curve.append(curve[-1] * (1 + t["pnl_pct"] / 100))
        
        ret = (curve[-1] - capital) / capital * 100
        peak = curve[0]
        mdd = 0
        for v in curve:
            if v > peak: peak = v
            dd = (peak - v) / peak * 100
            if dd > mdd: mdd = dd
        
        avg_r = sum(pnl) / len(pnl) if pnl else 0
        std_r = math.sqrt(sum((r - avg_r)**2 for r in pnl) / len(pnl)) if len(pnl) > 1 else 1
        sharpe = avg_r / std_r * math.sqrt(365) if std_r > 0 else 0
        pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
        
        results[s.name] = {
            "trades": len(trades), "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins)/len(trades)*100, 1),
            "return_pct": round(ret, 2),
            "mdd_pct": round(mdd, 2),
            "avg_win": round(sum(wins)/len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses)/len(losses), 2) if losses else 0,
            "profit_factor": round(pf, 2) if pf != float('inf') else "inf",
            "sharpe": round(sharpe, 2),
            "final": round(curve[-1], 2),
            "profit_abs": round(curve[-1] - capital, 2)
        }
    return results

# ============ 主入口 ============

def main():
    print("=" * 60)
    print("  Hanako Trading System - Backtest Engine v1.0")
    print("=" * 60)
    
    daily = load_klines("backtest/data/btc_daily.json")
    h4 = load_klines("backtest/data/btc_4h.json")
    print(f"\n  日线: {len(daily)} bars")
    print(f"  4h线: {len(h4)} bars")
    
    strategies = [
        lambda: EMACrossover(9, 21),
        lambda: EMACrossover(12, 26),
        lambda: EMARSICombo(21, 38, 50),
        lambda: EMARSICombo(21, 30, 55),
        lambda: EMARSICombo(55, 38, 50),
        lambda: ATRTrendFollow(21, 2.0),
        lambda: ATRTrendFollow(21, 3.0),
        lambda: ATRTrendFollow(55, 2.0),
        lambda: MACDStrategy(),
        lambda: BuyHold(),
    ]
    
    for name, data in [("日线", daily), ("4h线", h4)]:
        print(f"\n{'='*60}")
        print(f"  [{name}] 回测结果")
        print(f"{'='*60}")
        results = run_backtest(data, strategies)
        sorted_r = sorted(results.items(), key=lambda x: x[1].get("return_pct", -999) if "return_pct" in x[1] else -999, reverse=True)
        
        print(f"\n  {'策略':<28} {'收益%':>8} {'胜率':>6} {'交易':>5} {'回撤%':>8} {'夏普':>6}")
        print(f"  {'-'*65}")
        for n, r in sorted_r:
            if "error" in r:
                print(f"  {n:<28} {'ERROR':>8}")
                continue
            print(f"  {n:<28} {r['return_pct']:>7.1f}% {r['win_rate']:>5.1f}% {r['trades']:>5} {r['mdd_pct']:>7.1f}% {r['sharpe']:>5.2f}")
        
        if sorted_r and "error" not in sorted_r[0][1]:
            bn, b = sorted_r[0]
            print(f"\n  >>> 最优: {bn}")
            print(f"      收益: {b['return_pct']:+.2f}% (${b['profit_abs']:+,.0f})")
            print(f"      胜率: {b['win_rate']}% ({b['wins']}/{b['trades']})")
            print(f"      盈亏比: {b['profit_factor']}")
            print(f"      最大回撤: {b['mdd_pct']:.1f}%")
    
    # 保存
    out = {
        "time": datetime.now(timezone.utc).isoformat(),
        "daily": {k: v for k, v in run_backtest(daily, strategies).items()},
        "h4": {k: v for k, v in run_backtest(h4, strategies).items()}
    }
    with open("backtest/results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  结果已保存: backtest/results.json")

if __name__ == "__main__":
    main()
