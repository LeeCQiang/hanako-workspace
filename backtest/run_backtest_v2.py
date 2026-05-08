#!/usr/bin/env python3
"""
Hanako Trading System v2 - 短线优化回测
目标：胜率60%+，盈亏比1.5+，短周期交易
"""
import json, math, itertools
from datetime import datetime, timezone

# ============ 数据 ============
def load(filepath):
    with open(filepath) as f:
        raw = json.load(f)
    data = []
    for k in raw:
        data.append({
            "time": datetime.fromtimestamp(k[0]/1000, tz=timezone.utc),
            "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
            "close": float(k[4]), "volume": float(k[5])
        })
    return data

# ============ 指标 ============
def ema(data, p):
    r, m = [], 2/(p+1)
    for i in range(len(data)):
        if i == 0: r.append(data[i]["close"])
        else: r.append((data[i]["close"] - r[i-1])*m + r[i-1])
    return r

def sma(data, p):
    r = []
    for i in range(len(data)):
        if i < p-1: r.append(None)
        else: r.append(sum(d["close"] for d in data[i-p+1:i+1])/p)
    return r

def rsi(data, p=14):
    r, g, l = [None], [0], [0]
    for i in range(1, len(data)):
        d = data[i]["close"] - data[i-1]["close"]
        g.append(max(d,0)); l.append(max(-d,0))
        if i < p: r.append(None)
        elif i == p:
            ag, al = sum(g[1:p+1])/p, sum(l[1:p+1])/p
            rs = ag/al if al > 0 else 999
            r.append(100 - 100/(1+rs))
        else:
            ag = ((g[i-1]*(p-1) if g[i-1] else 0) + g[i]) / p
            al = ((l[i-1]*(p-1) if l[i-1] else 0) + l[i]) / p
            rs = ag/al if al > 0 else 999
            r.append(100 - 100/(1+rs))
    return r

def bb(data, p=20, std=2):
    """布林带"""
    mid = sma(data, p)
    band = []
    for i in range(len(data)):
        if mid[i] is None:
            band.append((None, None, None))
        else:
            s = math.sqrt(sum((data[j]["close"] - mid[i])**2 for j in range(i-p+1, i+1))/p)
            band.append((mid[i] - std*s, mid[i], mid[i] + std*s))
    return band  # (lower, mid, upper)

def stoch_rsi(data, p=14, k=3):
    """随机RSI (Stochastic RSI)"""
    r = rsi(data, p)
    result = []
    for i in range(len(data)):
        if i < p + k - 1 or r[i] is None:
            result.append(None)
            continue
        recent = [x for x in r[i-p+1:i+1] if x is not None]
        if not recent: result.append(None); continue
        mn, mx = min(recent), max(recent)
        stoch = (r[i] - mn)/(mx - mn)*100 if mx != mn else 50
        result.append(stoch)
    return result

def atr(data, p=14):
    r = [None]
    for i in range(1, len(data)):
        tr = max(data[i]["high"]-data[i]["low"],
                 abs(data[i]["high"]-data[i-1]["close"]),
                 abs(data[i]["low"]-data[i-1]["close"]))
        if i < p: r.append(tr)
        elif i == p: r.append(sum(r[1:p+1])/p)
        else: r.append((r[i-1]*(p-1) + tr)/p)
    return r

# ============ 策略 ============

class Strat:
    def __init__(self, name):
        self.name, self.trades = name, []
        self.in_pos, self.ep, self.ei = False, 0, 0
    def buy(self, i, p, r=""):
        self.in_pos, self.ep, self.ei = True, p, i
    def sell(self, i, p, r=""):
        if not self.in_pos: return
        pnl = (p - self.ep)/self.ep*100
        self.trades.append({"ei":self.ei,"xi":i,"ep":round(self.ep,2),"xp":round(p,2),
                           "pnl":round(pnl,2),"r":r,"et":str(self.ep),"xt":str(p)})
        self.in_pos = False

# --- 策略1: 布林带均值回归短线 ---
class BBMeanReversion(Strat):
    """布林带下轨买入，中轨/上轨卖出"""
    def __init__(self, bb_p=20, bb_std=2, sl_atr=1.5):
        super().__init__(f"BB{bb_p}_{bb_std}_MR")
        self.bb_p, self.bb_std, self.sl_atr = bb_p, bb_std, sl_atr
        self.sl_price, self.tp_pct = 0, 0.015
    def on_bar(self, i, d, ind):
        bbl, bbm, bbu = ind["bb"][i]
        a = ind["atr"][i]
        p = d[i]["close"]
        if bbl is None or a is None: return
        
        if not self.in_pos and p <= bbl:
            self.buy(i, p, f"下轨={p:.0f}")
            self.sl_price = p - a * self.sl_atr
        if self.in_pos:
            if p >= bbm or p <= self.sl_price:
                self.sell(i, p, "中轨/止损")

# --- 策略2: RSI超卖 + 短止损 ---
class RSIScalp(Strat):
    """RSI超卖区短平快"""
    def __init__(self, rsi_p=7, oversold=25, tp_pct=1.0, sl_pct=0.6):
        super().__init__(f"RSI{rsi_p}_Scalp_{oversold}")
        self.rsi_p, self.oversold = rsi_p, oversold
        self.tp_pct, self.sl_pct = tp_pct/100, sl_pct/100
        self.entry_p = 0
    def on_bar(self, i, d, ind):
        r = ind["rsi"][i]; p = d[i]["close"]
        if r is None: return
        if not self.in_pos and r < self.oversold:
            self.buy(i, p, f"RSI={r:.0f}")
            self.entry_p = p
        if self.in_pos:
            gain = (p - self.entry_p)/self.entry_p
            if gain >= self.tp_pct: self.sell(i, p, f"止盈{gain*100:.1f}%")
            elif gain <= -self.sl_pct: self.sell(i, p, f"止损{gain*100:.1f}%")

# --- 策略3: 多EMA短线共振 ---
class MultiEMA(Strat):
    """3/8/21 EMA 共振，趋势确认后入场"""
    def __init__(self):
        super().__init__("MultiEMA_3_8_21")
    def on_bar(self, i, d, ind):
        e3, e8, e21 = ind["ema3"][i], ind["ema8"][i], ind["ema21"][i]
        p = d[i]["close"]
        if None in (e3, e8, e21): return
        if not self.in_pos and p > e3 > e8 > e21 and p > e21*1.002:
            self.buy(i, p, "EMA顺排突破")
        if self.in_pos:
            if p < e8 or p < self.ep*0.993:
                self.sell(i, p, "破EMA8/止损")

# --- 策略4: 随机RSI + 均值回归 ---
class StochRSIStrat(Strat):
    """StochRSI < 10买入, > 80卖出"""
    def __init__(self, rsi_p=14, stoch_p=14, k=3, sl_pct=0.8, tp_pct=1.5):
        super().__init__(f"StochRSI_{rsi_p}_{stoch_p}")
        self.rsi_p, self.stoch_p, self.k = rsi_p, stoch_p, k
        self.sl_pct, self.tp_pct = sl_pct/100, tp_pct/100
        self.ep_entry = 0
    def on_bar(self, i, d, ind):
        s = ind["stoch_rsi"][i]; p = d[i]["close"]
        if s is None: return
        if not self.in_pos and s < 10:
            self.buy(i, p, f"StochRSI={s:.0f}")
            self.ep_entry = p
        if self.in_pos:
            gain = (p - self.ep_entry)/self.ep_entry
            if gain >= self.tp_pct: self.sell(i, p, f"止盈")
            elif gain <= -self.sl_pct: self.sell(i, p, f"止损")
            elif s is not None and s > 80: self.sell(i, p, f"超买{s:.0f}")

# --- 策略5: 多周期共振 ----
class MultiTFConfirm(Strat):
    """1h看趋势方向，15m找入场点"""
    def __init__(self, trend_ema=55, entry_rsi=30, tp_pct=1.2, sl_pct=0.7):
        super().__init__(f"MTF_{trend_ema}EMA_RSI{entry_rsi}")
        self.trend_ema = trend_ema
        self.entry_rsi = entry_rsi
        self.tp_pct, self.sl_pct = tp_pct/100, sl_pct/100
    def on_bar(self, i, d, ind):
        ema_t = ind["ema_trend"][i]
        r = ind["rsi"][i]; p = d[i]["close"]
        if ema_t is None or r is None: return
        trend_up = p > ema_t
        if not self.in_pos and trend_up and r < self.entry_rsi:
            self.buy(i, p, f"EMA上方 RSI={r:.0f}")
        if self.in_pos:
            gain = (p - self.ep)/self.ep
            if gain >= self.tp_pct: self.sell(i, p, f"止盈")
            elif gain <= -self.sl_pct: self.sell(i, p, f"止损")

# --- 策略6: 网格短线 ----
class GridScalp(Strat):
    """固定间距网格：0.5%止盈，0.4%止损"""
    def __init__(self, tp=0.5, sl=0.4):
        super().__init__(f"Grid_{tp}_{sl}")
        self.tp, self.sl = tp/100, sl/100
    def on_bar(self, i, d, ind):
        p = d[i]["close"]
        if not self.in_pos:
            self.buy(i, p, "开仓")
        if self.in_pos:
            gain = (p - self.ep)/self.ep
            if gain >= self.tp: self.sell(i, p, f"止盈{gain*100:.1f}%")
            elif gain <= -self.sl: self.sell(i, p, f"止损{abs(gain)*100:.1f}%")

# --- 策略7: 短周期布林带 + RSI 组合 ----
class BBMomentum(Strat):
    """布林带缩口突破 + RSI确认"""
    def __init__(self, bb_p=20, bb_std=2, rsi_p=7):
        super().__init__(f"BBM_{bb_p}_{rsi_p}")
        self.bb_p, self.bb_std, self.rsi_p = bb_p, bb_std, rsi_p
        self.sl_pct, self.tp_pct = 0.5/100, 1.0/100
    def on_bar(self, i, d, ind):
        bbl, bbm, bbu = ind["bb"][i]
        r = ind["rsi"][i]
        p = d[i]["close"]
        if bbl is None or r is None: return
        bw = (bbu - bbl)/bbm if bbm else 999
        if not self.in_pos and bw < 0.03 and r < 30:
            self.buy(i, p, f"缩口RSI={r:.0f}")
        if self.in_pos:
            gain = (p - self.ep)/self.ep
            if gain >= self.tp_pct: self.sell(i, p, f"止盈")
            elif gain <= -self.sl_pct: self.sell(i, p, f"止损")
            elif p >= bbu: self.sell(i, p, "上轨")

# ============ 回测 ============

def run(data, strats, capital=100000):
    ind = {
        "ema3": ema(data, 3), "ema8": ema(data, 8), "ema21": ema(data, 21),
        "ema_trend": ema(data, 55), "bb": bb(data, 20, 2),
        "rsi": rsi(data, 14), "rsi7": rsi(data, 7),
        "stoch_rsi": stoch_rsi(data, 14, 14), "atr": atr(data, 14)
    }
    ind["rsi"] = rsi(data, 14)
    
    results = {}
    for strat_cls in strats:
        s = strat_cls()
        for i in range(len(data)):
            s.on_bar(i, data, ind)
        if s.in_pos:
            s.sell(len(data)-1, data[-1]["close"], "close")
        
        t = s.trades
        if not t:
            results[s.name] = {"e": "no trades"}; continue
        
        pnl = [x["pnl"] for x in t]
        w = [x for x in pnl if x > 0]
        l = [x for x in pnl if x <= 0]
        curve = [capital]
        for x in t: curve.append(curve[-1] * (1 + x["pnl"]/100))
        
        ret = (curve[-1] - capital)/capital*100
        pk = curve[0]; mdd = 0
        for v in curve:
            if v > pk: pk = v
            dd = (pk - v)/pk*100
            if dd > mdd: mdd = dd
        
        avg_w = sum(w)/len(w) if w else 0
        avg_l = sum(l)/len(l) if l else 0
        pf = abs(sum(w)/sum(l)) if l and sum(l) != 0 else float('inf')
        wr = len(w)/len(t)*100 if t else 0
        
        results[s.name] = {
            "trades": len(t), "wins": len(w), "losses": len(l),
            "win_rate": round(wr, 1), "return_pct": round(ret, 2),
            "mdd_pct": round(mdd, 2), "avg_win": round(avg_w, 2),
            "avg_loss": round(avg_l, 2), "profit_factor": round(pf, 2),
            "final": round(curve[-1], 2),
            "profit_abs": round(curve[-1] - capital, 2)
        }
    return results

# ============ 报告 ============

def report(all_results, title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")
    print(f"  {'策略':<30} {'收益%':>7} {'胜率':>6} {'交易':>5} {'盈亏比':>7} {'回撤%':>7}")
    print(f"  {'-'*64}")
    
    best_wr, best_pf = None, None
    for label, results in sorted(all_results, key=lambda x: list(x[1].values())[0].get("return_pct", -999) if isinstance(list(x[1].values())[0], dict) else -999, reverse=True):
        if isinstance(results, dict) and "error" not in results:
            print(f"  {results['name']:<30} {results['return_pct']:>6.1f}% {results['win_rate']:>5.1f}% "
                  f"{results['trades']:>4} {results.get('profit_factor',0):>6.2f} {results['mdd_pct']:>6.1f}%")
            
            # 记录最佳达标策略
            r = results
            if r["win_rate"] >= 55 and r.get("profit_factor", 0) >= 1.3:
                if best_wr is None or r["win_rate"] > best_wr["win_rate"]:
                    best_wr = r
            if r.get("profit_factor", 0) >= 1.5 and r["win_rate"] >= 50:
                if best_pf is None or r["profit_factor"] > best_pf["profit_factor"]:
                    best_pf = r
    
    print(f"  {'-'*64}")
    if best_wr:
        print(f"\n  >>> 最佳胜率达标: {best_wr['name']}")
        print(f"     收益{best_wr['return_pct']:+.2f}% | 胜率{best_wr['win_rate']}% | 盈亏比{best_wr['profit_factor']}")
    if best_pf:
        print(f"\n  >>> 最佳盈亏比达标: {best_pf['name']}")
        print(f"     收益{best_pf['return_pct']:+.2f}% | 胜率{best_pf['win_rate']}% | 盈亏比{best_pf['profit_factor']}")

# ============ 参数优化 ============

def optimize(data, strat_class, params_grid, capital=100000):
    """自动参数调优"""
    print(f"\n  [优化] {strat_class.__name__}...")
    best = None
    for params in params_grid:
        s = strat_class(*params)
        ind = {"ema3":ema(data,3),"ema8":ema(data,8),"ema21":ema(data,21),
               "ema_trend":ema(data,55),"bb":bb(data,20,2),
               "rsi":rsi(data,14),"rsi7":rsi(data,7),
               "stoch_rsi":stoch_rsi(data,14,14),"atr":atr(data,14)}
        
        for i in range(len(data)):
            s.on_bar(i, data, ind)
        if s.in_pos: s.sell(len(data)-1, data[-1]["close"], "close")
        
        t = s.trades
        if not t: continue
        pnl = [x["pnl"] for x in t]
        w = [x for x in pnl if x > 0]
        l = [x for x in pnl if x <= 0]
        
        if not t: continue
        wr = len(w)/len(t)*100
        pf = abs(sum(w)/sum(l)) if l and sum(l) != 0 else 0
        ret = (sum(pnl)+1)**(252/len(data)*len(t)) - 1 if sum(pnl) > -len(t) else -100
        
        score = wr * 0.3 + pf * 20 + ret * 0.5
        if (best is None or score > best["score"]) and wr >= 55:
            best = {"params": params, "win_rate": round(wr,1), "profit_factor": round(pf,2),
                   "return_pct": round(ret,2), "trades": len(t), "score": round(score,1)}
    
    if best:
        print(f"    最优参数: {best['params']}")
        print(f"    胜率{best['win_rate']}% | 盈亏比{best['profit_factor']} | 收益{best['return_pct']:+.1f}% | {best['trades']}笔交易")
    return best

# ============ 主入口 ============

def main():
    print("=" * 70)
    print("  Hanako Trading System v2 - 短线策略优化回测")
    print("=" * 70)
    
    # 加载数据
    tfs = [
        ("15分钟线", load("backtest/data/btc_15m.json"), 15*60),
        ("30分钟线", load("backtest/data/btc_30m.json"), 30*60),
        ("1小时线",   load("backtest/data/btc_1h.json"), 60*60),
        ("4小时线",   load("backtest/data/btc_4h.json"), 4*60*60),
    ]
    
    for name, data, _ in tfs:
        print(f"\n  [{name}] {len(data)}根K线")
        
        # 策略列表
        strats = [RSIScalp, BBMeanReversion, MultiEMA, StochRSIStrat, MultiTFConfirm, GridScalp, BBMomentum]
        results = run(data, strats)
        
        # 按盈亏比排序显示
        sorted_r = sorted(results.values(), key=lambda x: x.get("profit_factor", 0) if isinstance(x, dict) and "profit_factor" in x[1] else 0, reverse=True)
        
        print(f"\n  {'策略':<30} {'收益%':>7} {'胜率':>6} {'交易':>5} {'盈亏比':>7} {'回撤%':>7}")
        print(f"  {'-'*64}")
        for r in sorted_r:
            if not isinstance(r, dict) or "error" in r: continue
            pf = r.get("profit_factor", 0)
            print(f"  {r['name']:<30} {r['return_pct']:>6.1f}% {r['win_rate']:>5.1f}% "
                  f"{r['trades']:>4} {pf:>6.2f} {r['mdd_pct']:>6.1f}%")
        
        # 标记达标策略
        print(f"\n  【达标策略筛选】")
        for r in sorted_r:
            if not isinstance(r, dict) or "error" in r: continue
            wr = r["win_rate"]; pf = r.get("profit_factor", 0)
            if wr >= 55 and pf >= 1.3:
                print(f"  ✅ {r['name']}: 胜率{wr}% 盈亏比{pf} 收益{r['return_pct']:+.1f}%")
            elif wr >= 50 and pf >= 1.5:
                print(f"  ✅ {r['name']}: 胜率{wr}% 盈亏比{pf} 收益{r['return_pct']:+.1f}%")
    
    # 参数自动优化（在1h和30m上）
    print(f"\n{'='*70}")
    print(f"  参数自动优化")
    print(f"{'='*70}")
    
    for tf_name, tf_data, _ in tfs[:2]:  # 只优化短周期
        print(f"\n  [{tf_name}] 参数扫描...")
        
        # RSI短线参数扫描
        optimize(tf_data, RSIScalp, 
                [(p, o, tp, sl) for p in [5,7,9,14] for o in [20,25,30] for tp in [0.8,1.0,1.2] for sl in [0.4,0.6,0.8]])
        
        # 布林带参数扫描
        optimize(tf_data, BBMeanReversion,
                [(p, s, a) for p in [15,20,25] for s in [1.5,2,2.5] for a in [1.0,1.5,2.0]])
        
        # 网格参数扫描
        optimize(tf_data, GridScalp,
                [(tp, sl) for tp in [0.3,0.4,0.5,0.6,0.8] for sl in [0.2,0.3,0.4,0.5]])
    
    print(f"\n{'='*70}")
    print(f"  回测完成！结果已保存")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
