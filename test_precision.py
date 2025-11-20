"""Test script to check Binance precision for all coins"""
import requests
import json

BASE_URL = "https://fapi.binance.com"

# Coin listesi (BTC ve ETH hariç)
COINS = [
    "BNBUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT", "DOTUSDT", "ADAUSDT",
    "ATOMUSDT", "NEARUSDT", "ARBUSDT", "OPUSDT", "APTUSDT", "SUIUSDT", "SEIUSDT",
    "AAVEUSDT", "LDOUSDT", "INJUSDT", "RUNEUSDT", "DOGEUSDT", "XRPUSDT", "UNIUSDT",
    "DYDXUSDT", "IMXUSDT", "RAYUSDT", "FTMUSDT", "EGLDUSDT", "FILUSDT", "GRTUSDT",
    "MKRUSDT", "SNXUSDT", "MINAUSDT", "ENSUSDT", "LRCUSDT", "CRVUSDT", "CHZUSDT",
    "GMTUSDT", "FLOWUSDT", "ICPUSDT", "STXUSDT", "XMRUSDT", "ZECUSDT", "KASUSDT",
    "JTOUSDT", "TIAUSDT", "JUPUSDT", "STRKUSDT", "BONKUSDT", "PYTHUSDT"
]

def count_decimals(s: str) -> int:
    if "." not in s:
        return 0
    frac = s.split(".")[1].rstrip("0")
    return len(frac)

print("=== BINANCE PRECISION ANALYSIS ===\n")

# Tüm coinlerin exchangeInfo'sunu çek
all_symbols_data = {}
for coin in COINS:
    try:
        # Symbol alias kontrolü
        symbol = "1000BONKUSDT" if coin == "BONKUSDT" else coin
        
        res = requests.get(BASE_URL + "/fapi/v1/exchangeInfo", params={"symbol": symbol}, timeout=10)
        data = res.json()
        symbols = data.get("symbols", [])
        
        if not symbols:
            print(f"{coin}: NO DATA")
            continue
            
        info = symbols[0]
        step_size = None
        market_step_size = None
        tick_size = None
        
        for f in info.get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                step_size = f.get("stepSize")
            elif f.get("filterType") == "MARKET_LOT_SIZE":
                market_step_size = f.get("stepSize")
            elif f.get("filterType") == "PRICE_FILTER":
                tick_size = f.get("tickSize")
        
        qty_decimals = count_decimals(str(step_size)) if step_size else 0
        market_qty_decimals = count_decimals(str(market_step_size)) if market_step_size else qty_decimals
        price_decimals = count_decimals(str(tick_size)) if tick_size else 4
        
        all_symbols_data[coin] = {
            "symbol": symbol,
            "stepSize": step_size,
            "marketStepSize": market_step_size,
            "tickSize": tick_size,
            "qty_decimals": qty_decimals,
            "market_qty_decimals": market_qty_decimals,
            "price_decimals": price_decimals,
        }
        
        print(f"{coin} ({symbol}):")
        print(f"  LOT_SIZE stepSize: {step_size} ({qty_decimals} decimals)")
        print(f"  MARKET_LOT_SIZE stepSize: {market_step_size} ({market_qty_decimals} decimals)")
        print(f"  PRICE_FILTER tickSize: {tick_size} ({price_decimals} decimals)")
        print()
        
    except Exception as e:
        print(f"{coin}: ERROR - {e}\n")

# Sorunlu coinleri özel test et
print("\n=== PRECISION ISSUE ANALYSIS ===\n")
problematic = ["RUNEUSDT", "FILUSDT", "GMTUSDT", "DYDXUSDT", "ATOMUSDT"]

for coin in problematic:
    if coin in all_symbols_data:
        data = all_symbols_data[coin]
        print(f"{coin}:")
        print(f"  marketStepSize: {data['marketStepSize']}")
        print(f"  market_qty_decimals: {data['market_qty_decimals']}")
        
        # Test quantity hesaplama
        entry = 0.863 if coin == "RUNEUSDT" else (1.658 if coin == "FILUSDT" else (0.02523 if coin == "GMTUSDT" else (0.322 if coin == "DYDXUSDT" else 3.052)))
        margin = 5.0
        leverage = 20
        notional = margin * leverage  # 100 USDT
        raw_qty = notional / entry
        
        print(f"  Test: entry={entry} -> notional={notional} -> raw_qty={raw_qty}")
        
        # stepSize'a göre yuvarla
        if data['marketStepSize']:
            step = float(data['marketStepSize'])
            import math
            floored_qty = math.floor(raw_qty / step) * step
            print(f"  floored_qty (math): {floored_qty}")
            
            # Formatla
            decimals = data['market_qty_decimals']
            formatted = f"{floored_qty:.{decimals}f}".rstrip('0').rstrip('.')
            if not formatted or formatted == '.':
                formatted = f"{floored_qty:.{decimals}f}"
            print(f"  formatted ({decimals} decimals): '{formatted}'")
            print(f"  formatted repr: {repr(formatted)}")
        print()

