#!/usr/bin/env python3
"""
Hanako Trading System v2 - 短线优化回测
目标：胜率60%+，盈亏比1.5+，短周期交易
"""
import json, math
from datetime import datetime, timezone

def load(f):
    with open(f) as fp:
        raw = json.load(fp)
    return [{"time": datetime.fromtimestamp(k[0]/1000, tz=timezone.utc),
             "open": float(k[1]),"high": float(k[2]),"low": float(k[3]),
             "close": float(k[4]),"volume": float(k[5])} for k in raw]

def ema(d,p):
    r,m=[],2/(p+1)
    for i in range(len(d)):
        if i==0: r.append(d[i]["close"])
        else: r.append((d[i]["close"]-r[i-1])*m+r[i-1])
    return r

def sma(d,p):
    r=[]
    for i in range(len(d)):
        if i<p-1: r.append(None)
        else: r.append(sum(x["close"] for x in d[i-p+1:i+1])/p)
    return r

def rsi(d,p=14):
    r,g,l=[None],[0],[0]
    for i in range(1,len(d)):
        df=d[i]["close"]-d[i-1]["close"]
        g.append(max(df,0));l.append(max(-df,0))
        if i<p: r.append(None)
        elif i==p:
            ag,al=sum(g[1:p+1])/p,sum(l[1:p+1])/p
            rs=ag/al if al>0 else 999
            r.append(100-100/(1+rs))
        else:
            ag=(g[i-1]*(p-1)+g[i])/p;al=(l[i-1]*(p-1)+l[i])/p
            rs=ag/al if al>0 else 999
            r.append(100-100/(1+rs))
    return r

def bb(d,p=20,s=2):
    mid=sma(d,p)
    b=[]
    for i in range(len(d)):
        if mid[i] is None: b.append((None,None,None))
        else:
            sd=math.sqrt(sum((d[j]["close"]-mid[i])**2 for j in range(i-p+1,i+1))/p)
            b.append((mid[i]-s*sd,mid[i],mid[i]+s*sd))
    return b

def stoch_rsi(d,p=14,k=3):
    r=rsi(d,p)
    res=[]
    for i in range(len(d)):
        if i<p+k-1 or r[i] is None: res.append(None);continue
        recent=[x for x in r[i-p+1:i+1] if x is not None]
        if not recent: res.append(None);continue
        mn,mx=min(recent),max(recent)
        res.append((r[i]-mn)/(mx-mn)*100 if mx!=mn else 50)
    return res

def atr(d,p=14):
    r=[None]
    for i in range(1,len(d)):
        tr=max(d[i]["high"]-d[i]["low"],abs(d[i]["high"]-d[i-1]["close"]),abs(d[i]["low"]-d[i-1]["close"]))
        if i<p: r.append(tr)
        elif i==p: r.append(sum(r[1:p+1])/p)
        else: r.append((r[i-1]*(p-1)+tr)/p)
    return r

class Strat:
    def __init__(self,n):
        self.name,self.trades,self.in_pos,self.ep,self.ei=n,[],False,0,0
    def buy(self,i,p,r=""):
        self.in_pos,self.ep,self.ei=True,p,i;self.ep_entry=p
    def sell(self,i,p,r=""):
        if not self.in_pos: return
        pnl=(p-self.ep)/self.ep*100
        self.trades.append({"ei":self.ei,"xi":i,"ep":round(self.ep,2),"xp":round(p,2),"pnl":round(pnl,2),"r":r})
        self.in_pos=False

class RSIScalp(Strat):
    def __init__(s,pr=7,os=25,tp=1.0,sl=0.6):
        super().__init__(f"RSIs{pr}_{os}");s.pr,s.os,s.tp,s.sl=pr,os,tp/100,sl/100
    def on_bar(s,i,d,ind):
        r=ind["rsi"][i];p=d[i]["close"]
        if r is None: return
        if not s.in_pos and r<s.os: s.buy(i,p,f"RSI{r:.0f}")
        if s.in_pos:
            g=(p-s.ep)/s.ep
            if g>=s.tp: s.sell(i,p,f"TP{g*100:.1f}%")
            elif g<=-s.sl: s.sell(i,p,f"SL{abs(g)*100:.1f}%")

class BBMeanRev(Strat):
    def __init__(s,p=20,std=2,sl=1.5):
        super().__init__(f"BB{p}_{std}");s.p,s.std,s.sl=p,std,sl
    def on_bar(s,i,d,ind):
        bl,bm,_=ind["bb"][i];a=ind["atr"][i];p=d[i]["close"]
        if bl is None or a is None: return
        if not s.in_pos and p<=bl: s.buy(i,p,f"L{b:.0f}");s.sp=p-a*s.sl
        if s.in_pos and (p>=bm or p<=s.sp): s.sell(i,p,"E/L")

class MultiEMAStrat(Strat):
    def __init__(s):
        super().__init__("MEM3_8_21")
    def on_bar(s,i,d,ind):
        e3,e8,e21=ind["e3"][i],ind["e8"][i],ind["e21"][i];p=d[i]["close"]
        if None in (e3,e8,e21): return
        if not s.in_pos and p>e3>e8>e21 and p>e21*1.002: s.buy(i,p,"↑")
        if s.in_pos and (p<e8 or p<s.ep*0.993): s.sell(i,p,"↓")

class StochRSIStrat(Strat):
    def __init__(s):
        super().__init__("StRSI")
    def on_bar(s,i,d,ind):
        sr=ind["srsi"][i];p=d[i]["close"]
        if sr is None: return
        if not s.in_pos and sr<10: s.buy(i,p,f"S{sr:.0f}")
        if s.in_pos:
            g=(p-s.ep)/s.ep
            if g>=0.015: s.sell(i,p,"TP")
            elif g<=-0.008: s.sell(i,p,"SL")
            elif sr>80: s.sell(i,p,"O{sr:.0f}")

class MTFConfirm(Strat):
    def __init__(s,en=55,er=30,tp=1.2,sl=0.7):
        super().__init__(f"MTF{en}_{er}");s.en,s.er,s.tp,s.sl=en,er,tp/100,sl/100
    def on_bar(s,i,d,ind):
        et=ind["et"][i];r=ind["rsi"][i];p=d[i]["close"]
        if et is None or r is None: return
        if not s.in_pos and p>et and r<s.er: s.buy(i,p,f"R{r:.0f}")
        if s.in_pos:
            g=(p-s.ep)/s.ep
            if g>=s.tp: s.sell(i,p,"TP")
            elif g<=-s.sl: s.sell(i,p,"SL")

class GridScalp(Strat):
    def __init__(s,tp=0.5,sl=0.4):
        super().__init__(f"Grid{tp}_{sl}");s.tp,s.sl=tp/100,sl/100
    def on_bar(s,i,d,ind):
        p=d[i]["close"]
        if not s.in_pos: s.buy(i,p,"G")
        if s.in_pos:
            g=(p-s.ep)/s.ep
            if g>=s.tp: s.sell(i,p,f"TP")
            elif g<=-s.sl: s.sell(i,p,f"SL")

def run(data,strats,cap=100000):
    ind={"e3":ema(data,3),"e8":ema(data,8),"e21":ema(data,21),
         "et":ema(data,55),"bb":bb(data,20,2),"rsi":rsi(data,14),
         "srsi":stoch_rsi(data,14,14),"atr":atr(data,14)}
    res={}
    for sc in strats:
        s=sc()
        for i in range(len(data)): s.on_bar(i,data,ind)
        if s.in_pos: s.sell(len(data)-1,data[-1]["close"],"C")
        t=s.trades
        if not t: res[s.name]={"e":"0"};continue
        pnl=[x["pnl"] for x in t]
        w=[x for x in pnl if x>0];l=[x for x in pnl if x<=0]
        cv=[cap]
        for x in t: cv.append(cv[-1]*(1+x["pnl"]/100))
        ret=(cv[-1]-cap)/cap*100
        pk=cv[0];mdd=0
        for v in cv:
            if v>pk:pk=v
            dd=(pk-v)/pk*100
            if dd>mdd:mdd=dd
        aw=sum(w)/len(w) if w else 0
        al=sum(l)/len(l) if l else 0
        pf=abs(sum(w)/sum(l)) if l and sum(l)!=0 else 999
        res[s.name]={"trades":len(t),"wins":len(w),"losses":len(l),
            "wr":round(len(w)/len(t)*100,1),"ret":round(ret,2),"mdd":round(mdd,2),
            "aw":round(aw,2),"al":round(al,2),"pf":round(pf,2)}
    return res

def main():
    print("="*70)
    print("  Hanako Trading System v2 - 短线策略优化回测")
    print("="*70)
    
    tfs=[("15分钟线(15天)",load("backtest/data/btc_15m.json")),
         ("30分钟线(30天)",load("backtest/data/btc_30m.json")),
         ("1小时线(90天)",load("backtest/data/btc_1h.json")),
         ("4小时线(180天)",load("backtest/data/btc_4h.json"))]
    
    all_results={}
    for name,data in tfs:
        print(f"\n{'='*70}")
        print(f"  [{name}] {len(data)}根K线")
        print(f"{'='*70}")
        
        results=run(data,[RSIScalp,BBMeanRev,MultiEMAStrat,StochRSIStrat,MTFConfirm,GridScalp])
        all_results[name]=results
        
        sorted_r=sorted(results.items(),key=lambda x:x[1].get("pf",0),reverse=True)
        print(f"\n  {'策略':<30} {'收益%':>7} {'胜率':>6} {'交易':>5} {'盈亏比':>6} {'回撤%':>7}")
        print(f"  {'-'*63}")
        for n,r in sorted_r:
            if "e" in r: continue
            print(f"  {n:<30} {r['ret']:>6.1f}% {r['wr']:>5.1f}% {r['trades']:>4} {r['pf']:>5.2f} {r['mdd']:>6.1f}%")
        
        print(f"\n  ✅ 达标策略（胜率≥55% 且 盈亏比≥1.3）:")
        for n,r in sorted_r:
            if "e" in r: continue
            if r["wr"]>=55 and r["pf"]>=1.3:
                print(f"    ★ {n}: 收益{r['ret']:+.1f}% | 胜率{r['wr']}% | 盈亏比{r['pf']} | 回撤{r['mdd']}%")
            elif r["wr"]>=50 and r["pf"]>=1.5:
                print(f"    ☆ {n}: 收益{r['ret']:+.1f}% | 胜率{r['wr']}% | 盈亏比{r['pf']} | 回撤{r['mdd']}%")
    
    # 保存结果
    with open("backtest/results.json","w") as f:
        json.dump({"time":str(datetime.now(timezone.utc).isoformat()),"v2":all_results},f,indent=2)
    print(f"\n✅ 结果已保存到 backtest/results.json")

if __name__=="__main__":
    main()
