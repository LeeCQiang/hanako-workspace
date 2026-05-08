#!/usr/bin/env python3
"""
Hanako Trading Bot — 7x24 自动交易监控
运行于 GitHub Actions，每 30 分钟检查一次
"""
import os
import json
import time
import urllib.request
from datetime import datetime, timezone

# ============ 配置 ============
API_BASE = "https://ai4trade.ai"
TOKEN = os.environ.get("AI_TRADER_TOKEN", "")
STATE_FILE = "bot-state.json"
LOG_FILE = "bot-log.jsonl"

# 当前持仓配置
POSITION = {
    "symbol": "BTC",
    "direction": "LONG",
    "entry_price": 79710.0,
    "quantity": 0.997,
    "leverage": 10,
    "stop_loss": 76952.0,
    "take_profit_1": 82774.0,
    "take_profit_2": 85000.0,
    "signal_id": 386120
}

# 跟单配置
FOLLOWING = [
    {"name": "byonce_aiai", "agent_id": 1460},
    {"name": "backplex", "agent_id": 4966}
]

# ============ 工具函数 ============

def api_get(path):
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "User-Agent": "HanakoBot/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

def api_post(path, data):
    url = f"{API_BASE}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "HanakoBot/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"position_status": "open", "entry_time": "2026-05-08T13:32:00Z"}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def log_event(event_type, data):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "data": data
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry

# ============ 核心逻辑 ============

def check_btc_price():
    """获取当前 BTC 价格"""
    result = api_get("/api/price?symbol=BTC&market=crypto")
    price = result.get("price")
    if not price:
        log_event("error", {"msg": "获取BTC价格失败", "raw": result})
        return None
    return float(price)

def check_position_status(price):
    """检查仓位是否触达止盈/止损"""
    if price is None:
        return "unknown", 0
    
    pnl_pct = (price - POSITION["entry_price"]) / POSITION["entry_price"] * 100
    pnl_dollar = (price - POSITION["entry_price"]) * POSITION["quantity"]
    
    action = "hold"
    reason = ""
    
    # 检查止损
    if price <= POSITION["stop_loss"]:
        action = "close_stop_loss"
        reason = f"触达止损 ${POSITION['stop_loss']:.0f}"
    
    # 检查止盈1
    if price >= POSITION["take_profit_1"] and price < POSITION["take_profit_2"]:
        action = "close_tp1"
        reason = f"触达止盈1 ${POSITION['take_profit_1']:.0f}"
    
    # 检查止盈2
    if price >= POSITION["take_profit_2"]:
        action = "close_tp2"
        reason = f"触达止盈2 ${POSITION['take_profit_2']:.0f}"
    
    return action, round(pnl_pct, 2), round(pnl_dollar, 2), reason

def close_position(price, reason):
    """平仓"""
    result = api_post("/api/signals/realtime", {
        "action": "sell",
        "symbol": "BTC",
        "price": price,
        "quantity": POSITION["quantity"],
        "market": "crypto",
        "content": f"[HanakoBot Auto Close] {reason} | PnL: ${((price-POSITION['entry_price'])*POSITION['quantity']):.0f}",
        "executed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    })
    log_event("close_position", {
        "price": price,
        "reason": reason,
        "pnl_dollar": round((price - POSITION["entry_price"]) * POSITION["quantity"], 2),
        "result": result
    })
    return result

def check_following_signals():
    """检查跟单对象的最新信号"""
    signals = {}
    for trader in FOLLOWING:
        result = api_get(f"/api/signals/{trader['agent_id']}?limit=3")
        signals[trader["name"]] = result
    return signals

def generate_report(price, pnl_pct, pnl_dollar, action, signals):
    """生成文本报告"""
    now = datetime.now(timezone.utc)
    report = [
        f"=== Hanako Bot Report @ {now.strftime('%Y-%m-%d %H:%M UTC')} ===",
        f"BTC: ${price:,.0f} | 持仓: {action}",
        f"PnL: {pnl_pct:+.2f}% (${pnl_dollar:+,.0f})",
    ]
    if action != "hold":
        report.append(f"⚡ 触发操作: {action}")
    for name, sig_data in signals.items():
        if isinstance(sig_data, dict) and "signals" in sig_data:
            recent = sig_data["signals"][:2] if sig_data["signals"] else []
            report.append(f"  {name}: {len(recent)}条最新信号")
    report.append("=" * 40)
    return "\n".join(report)

# ============ 主入口 ============

def main():
    # 1. 加载状态
    state = load_state()
    
    # 2. 获取价格
    price = check_btc_price()
    if price is None:
        log_event("check_failed", {"reason": "price_fetch_failed"})
        print("❌ 获取价格失败，跳过本轮")
        return
    
    # 3. 检查仓位
    action, pnl_pct, pnl_dollar, reason = check_position_status(price)
    
    # 4. 检查跟单
    signals = check_following_signals()
    
    # 5. 生成报告
    report = generate_report(price, pnl_pct, pnl_dollar, state["position_status"], signals)
    print(report)
    log_event("check", {
        "price": price,
        "pnl_pct": pnl_pct,
        "pnl_dollar": pnl_dollar,
        "status": state["position_status"],
        "action": action
    })
    
    # 6. 如果触达止盈/止损，执行平仓
    if action.startswith("close"):
        result = close_position(price, reason)
        state["position_status"] = "closed"
        state["close_time"] = datetime.now(timezone.utc).isoformat()
        state["close_reason"] = reason
        state["final_pnl"] = pnl_dollar
        print(f"✅ 已平仓: {reason}")
    
    # 7. 保存状态
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    state["last_price"] = price
    save_state(state)

if __name__ == "__main__":
    main()
