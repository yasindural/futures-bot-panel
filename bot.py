"""Binance Futures PnL tabanlı otomatik işlem botu (sıfırdan yazılmış).

Özellikler
----------
* TradingView webhook endpoint
* Margin tabanlı miktar hesaplama (BOT_MARGIN_USDT * leverage / entry)
* Binance precision kurallarına tam uyum (Decimal ile step/tick quantize)
* USDT bazlı PnL trailing stop (peak PnL'e göre SL güncelleme)
* Aynı yönde açık pozisyonu tekrar açmayı engelleme, zıt yönü otomatik kapatma
* Günlük realized PnL limiti (DAILY_MAX_LOSS)

NOT: Gerçek hesapta kullanmadan önce ortam değişkenlerinizi ayarlayın ve test edin.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, getcontext
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session, make_response
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

# ------------------------------------------------------------------------------
# Global init & configuration
# ------------------------------------------------------------------------------

getcontext().prec = 28
load_dotenv()

BOT_VERSION = "PNL_TRAIL_V2"
print(f"### BOT VERSION: {BOT_VERSION} ###")

API_KEY = os.getenv("BINANCE_API_KEY") or ""
API_SECRET = os.getenv("BINANCE_API_SECRET") or ""
BASE_URL = os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com")

DEFAULT_LEVERAGE = int(os.getenv("BOT_LEVERAGE", "20"))
BOT_MARGIN_USDT = Decimal(os.getenv("BOT_MARGIN_USDT", "5"))
DAILY_MAX_LOSS = Decimal(os.getenv("BOT_DAILY_MAX_LOSS", "-100"))
INITIAL_SL_ROE = Decimal(os.getenv("BOT_INITIAL_SL_ROE", "-20"))  # ilk SL ROI (%)
USE_DYNAMIC_PRECISION = os.getenv("DYNAMIC_PRECISION", "1").strip().lower() in ("1", "true", "yes", "on")
WATCH_INTERVAL_SECONDS = float(os.getenv("BOT_WATCH_INTERVAL_SECONDS", "3"))

SYMBOL_ALIASES: Dict[str, str] = {
    "BONKUSDT": "1000BONKUSDT",
}

http_session = requests.Session()
if API_KEY:
    http_session.headers.update({"X-MBX-APIKEY": API_KEY})

app = Flask(__name__)
CORS(
    app,
    resources={r"/api/*": {"origins": ["http://localhost:5173"]}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))


@app.after_request
def apply_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "http://localhost:5173"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


@app.route("/api/<path:_unused>", methods=["OPTIONS"])
def cors_preflight(_unused):
    response = make_response("", 204)
    response.headers["Access-Control-Allow-Origin"] = "http://localhost:5173"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


@app.route("/api/debug-cors", methods=["GET"])
def debug_cors():
    return jsonify({"status": "ok"})

open_positions: Dict[str, Dict[str, Any]] = {}
watcher_threads: Dict[str, threading.Thread] = {}
state_lock = threading.Lock()

# Paths
BASE_DIR = Path(__file__).parent
USERS_FILE = BASE_DIR / "users.json"
CONFIG_FILE = BASE_DIR / "bot_config.json"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)


# ------------------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Config management (bot_config.json)
# ------------------------------------------------------------------------------


def load_config() -> Dict[str, Any]:
    """Load bot config from bot_config.json, create default if missing."""
    default_config = {
        "BOT_MARGIN_USDT": float(BOT_MARGIN_USDT),
        "BOT_LEVERAGE": DEFAULT_LEVERAGE,
        "BOT_DAILY_MAX_LOSS": float(DAILY_MAX_LOSS),
        "BOT_INITIAL_SL_ROE": float(INITIAL_SL_ROE),
        "BOT_WATCH_INTERVAL_SECONDS": WATCH_INTERVAL_SECONDS,
        "USE_DYNAMIC_PRECISION": USE_DYNAMIC_PRECISION,
        "TEST_MODE": False,
        "AUTO_LOGOUT_MINUTES": 30,
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_config.update(loaded)
        except Exception as exc:
            logger.warning(f"Config load error: {exc}, using defaults")
    else:
        save_config(default_config)
    return default_config


def save_config(config: Dict[str, Any]) -> None:
    """Save bot config to bot_config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("Config saved")
    except Exception as exc:
        logger.error(f"Config save error: {exc}")


def apply_config(config: Dict[str, Any]) -> None:
    """Apply config values to global variables."""
    global DEFAULT_LEVERAGE, BOT_MARGIN_USDT, DAILY_MAX_LOSS, INITIAL_SL_ROE
    global USE_DYNAMIC_PRECISION, WATCH_INTERVAL_SECONDS
    DEFAULT_LEVERAGE = int(config.get("BOT_LEVERAGE", DEFAULT_LEVERAGE))
    BOT_MARGIN_USDT = Decimal(str(config.get("BOT_MARGIN_USDT", BOT_MARGIN_USDT)))
    DAILY_MAX_LOSS = Decimal(str(config.get("BOT_DAILY_MAX_LOSS", DAILY_MAX_LOSS)))
    INITIAL_SL_ROE = Decimal(str(config.get("BOT_INITIAL_SL_ROE", INITIAL_SL_ROE)))
    USE_DYNAMIC_PRECISION = bool(config.get("USE_DYNAMIC_PRECISION", USE_DYNAMIC_PRECISION))
    WATCH_INTERVAL_SECONDS = float(config.get("BOT_WATCH_INTERVAL_SECONDS", WATCH_INTERVAL_SECONDS))


# Load and apply config on startup
_config_data = load_config()
apply_config(_config_data)


# ------------------------------------------------------------------------------
# User management (users.json)
# ------------------------------------------------------------------------------


def load_users() -> List[Dict[str, Any]]:
    """Load users from users.json, create default admin if missing."""
    default_users = [
        {
            "username": "admin",
            "password_hash": generate_password_hash("admin"),
            "role": "admin",
            "api_key": "",
            "api_secret": "",
            "theme_preference": "dark",
        }
    ]
    if USERS_FILE.exists():
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if loaded:
                    return loaded
        except Exception as exc:
            logger.warning(f"Users load error: {exc}, creating default")
    else:
        save_users(default_users)
        logger.info("Created default users.json with admin/admin")
    return default_users


def save_users(users: List[Dict[str, Any]]) -> None:
    """Save users to users.json."""
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"Users save error: {exc}")


def find_user(username: str) -> Optional[Dict[str, Any]]:
    """Find user by username."""
    users = load_users()
    for user in users:
        if user.get("username") == username:
            return user
    return None


def create_user(username: str, password: str, role: str, api_key: str = "", api_secret: str = "") -> bool:
    """Create new user. Returns True if created, False if username exists."""
    users = load_users()
    if find_user(username):
        return False
    users.append(
        {
            "username": username,
            "password_hash": generate_password_hash(password),
            "role": role,
            "api_key": api_key,
            "api_secret": api_secret,
            "theme_preference": "dark",
        }
    )
    save_users(users)
    logger.info(f"User created: {username} ({role})")
    return True


def mask_api_key(key: str) -> str:
    """Mask API key for display: ****ABCD"""
    if not key or len(key) < 4:
        return "****"
    return f"****{key[-4:]}"


# ------------------------------------------------------------------------------
# Auth decorator
# ------------------------------------------------------------------------------


def login_required(f):
    """Decorator to require login for endpoints."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return jsonify({"status": "error", "message": "Login required"}), 401
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Decorator to require admin role."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return jsonify({"status": "error", "message": "Login required"}), 401
        if session.get("user", {}).get("role") != "admin":
            return jsonify({"status": "error", "message": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


# ------------------------------------------------------------------------------
# Dashboard helpers
# ------------------------------------------------------------------------------


def _to_serializable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_to_serializable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_serializable(val) for key, val in value.items()}
    return value


def _snapshot_positions() -> Dict[str, Dict[str, Any]]:
    with state_lock:
        return {key: dict(val) for key, val in open_positions.items()}


# ------------------------------------------------------------------------------
# Precision helpers
# ------------------------------------------------------------------------------

def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class PrecisionCache:
    _cache: Dict[str, Dict[str, Any]] = {}
    _lock = threading.Lock()

    @staticmethod
    def _count_decimals(text: str) -> int:
        if "." not in text:
            return 0
        return len(text.split(".")[1].rstrip("0"))

    @classmethod
    def get(cls, symbol: str) -> Dict[str, Any]:
        sym = symbol.upper()
        with cls._lock:
            cached = cls._cache.get(sym)
            if cached:
                return cached

        if not USE_DYNAMIC_PRECISION:
            data = {
                "stepSize": Decimal("0"),
                "marketStepSize": Decimal("0"),
                "tickSize": Decimal("0.0001"),
                "qty_decimals": 3,
                "market_qty_decimals": 3,
                "price_decimals": 4,
            }
            with cls._lock:
                cls._cache[sym] = data
            return data

        try:
            resp = http_session.get(f"{BASE_URL}/fapi/v1/exchangeInfo", params={"symbol": sym}, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
            symbols = payload.get("symbols") or []
            if not symbols:
                raise RuntimeError(f"exchangeInfo empty for {sym}")
            info = None
            for item in symbols:
                if str(item.get("symbol")).upper() == sym:
                    info = item
                    break
            if info is None:
                raise RuntimeError(f"symbol {sym} not present in exchangeInfo response")
            step_size = None
            market_step_size = None
            tick_size = None
            for flt in info.get("filters", []):
                if flt.get("filterType") == "LOT_SIZE":
                    step_size = flt.get("stepSize")
                elif flt.get("filterType") == "MARKET_LOT_SIZE":
                    market_step_size = flt.get("stepSize")
                elif flt.get("filterType") == "PRICE_FILTER":
                    tick_size = flt.get("tickSize")
            if (step_size is None and market_step_size is None) or tick_size is None:
                raise RuntimeError(
                    f"missing filters for {sym}: step={step_size} market_step={market_step_size} tick={tick_size}"
                )
            qty_decimals = cls._count_decimals(str(step_size))
            market_qty_decimals = cls._count_decimals(str(market_step_size)) if market_step_size else qty_decimals
            price_decimals = cls._count_decimals(str(tick_size))
            data = {
                "stepSize": Decimal(str(step_size)) if step_size else Decimal("0"),
                "marketStepSize": Decimal(str(market_step_size)) if market_step_size else Decimal("0"),
                "tickSize": Decimal(str(tick_size)),
                "qty_decimals": qty_decimals,
                "market_qty_decimals": market_qty_decimals,
                "price_decimals": price_decimals,
            }
            with cls._lock:
                cls._cache[sym] = data
            return data
        except Exception as exc:
            print(f"[PRECISION] exchangeInfo error for {sym}: {exc}")
            data = {
                "stepSize": Decimal("0"),
                "marketStepSize": Decimal("0"),
                "tickSize": Decimal("0.0001"),
                "qty_decimals": 3,
                "market_qty_decimals": 3,
                "price_decimals": 4,
            }
            with cls._lock:
                cls._cache[sym] = data
            return data


def _format_decimal(value: Decimal, decimals: int) -> str:
    quant = Decimal("1") if decimals == 0 else Decimal(f"1e-{decimals}")
    return f"{value.quantize(quant, rounding=ROUND_DOWN):.{decimals}f}"


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    units = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def _ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    units = (value / step)
    integral = units.to_integral_value(rounding=ROUND_DOWN)
    if units == integral:
        return value
    return (integral + 1) * step


def _floor_quantity(symbol: str, qty: Decimal, precision: Optional[Dict[str, Any]] = None) -> Decimal:
    precision = precision or PrecisionCache.get(symbol)
    step = precision["marketStepSize"] if precision["marketStepSize"] > 0 else precision["stepSize"]
    if step > 0:
        return _floor_to_step(qty, step)
    return qty.quantize(Decimal("0.001"), rounding=ROUND_DOWN)


def _format_quantity(symbol: str, qty: Decimal, precision: Optional[Dict[str, Any]] = None) -> str:
    precision = precision or PrecisionCache.get(symbol)
    decimals = precision["market_qty_decimals"] if precision["marketStepSize"] > 0 else precision["qty_decimals"]
    decimals = decimals if decimals is not None else 3
    return _format_decimal(qty, decimals)


def _format_price(symbol: str, price: Decimal, position_side: str, precision: Optional[Dict[str, Any]] = None) -> str:
    precision = precision or PrecisionCache.get(symbol)
    tick = precision["tickSize"] if precision["tickSize"] > 0 else Decimal("0.0001")
    decimals = precision["price_decimals"] if precision["price_decimals"] is not None else 4
    if position_side.upper() == "LONG":
        adj = _floor_to_step(price, tick)
    else:
        adj = _ceil_to_step(price, tick)
    return _format_decimal(adj, decimals)


# ------------------------------------------------------------------------------
# Binance HTTP helpers
# ------------------------------------------------------------------------------

def _ensure_secret() -> None:
    if not API_SECRET:
        raise RuntimeError("BINANCE_API_SECRET not configured")


def _sign(query: str) -> str:
    _ensure_secret()
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()


def _signed_request(method: str, path: str, params: Dict[str, Any]) -> requests.Response:
    payload: Dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, Decimal):
            payload[key] = str(value)
        else:
            payload[key] = value
    payload["timestamp"] = int(time.time() * 1000)
    query = urlencode(payload, doseq=True)
    payload["signature"] = _sign(query)
    url = BASE_URL + path
    method = method.upper()
    if method == "GET":
        return http_session.get(url, params=payload, timeout=10)
    if method == "POST":
        return http_session.post(url, params=payload, timeout=10)
    if method == "DELETE":
        return http_session.delete(url, params=payload, timeout=10)
    raise ValueError(f"Unsupported method {method}")


def _signed_get(path: str, params: Dict[str, Any]) -> requests.Response:
    return _signed_request("GET", path, params)


def _signed_post(path: str, params: Dict[str, Any]) -> requests.Response:
    return _signed_request("POST", path, params)


def _signed_delete(path: str, params: Dict[str, Any]) -> requests.Response:
    return _signed_request("DELETE", path, params)


# ------------------------------------------------------------------------------
# Binance API wrappers
# ------------------------------------------------------------------------------

def get_position_risk(symbol: str, position_side: str) -> Dict[str, Any]:
    res = _signed_get("/fapi/v2/positionRisk", {"symbol": symbol})
    data = res.json()
    if isinstance(data, dict):
        data = [data]
    for item in data:
        if str(item.get("symbol")).upper() == symbol.upper() and str(item.get("positionSide")).upper() == position_side.upper():
            return item
    return {}


def get_open_orders(symbol: str) -> Any:
    try:
        return _signed_get("/fapi/v1/openOrders", {"symbol": symbol}).json()
    except Exception:
        return []


def cancel_order(symbol: str, order_id: int) -> Dict[str, Any]:
    try:
        return _signed_delete("/fapi/v1/order", {"symbol": symbol, "orderId": order_id}).json()
    except Exception as exc:
        return {"error": str(exc)}


def cancel_existing_sl_orders(symbol: str, position_side: str) -> None:
    orders = get_open_orders(symbol) or []
    for order in orders:
        try:
            if (
                str(order.get("type")) == "STOP_MARKET"
                and bool(order.get("closePosition")) is True
                and str(order.get("positionSide", "")).upper() == position_side.upper()
            ):
                oid = order.get("orderId")
                resp = cancel_order(symbol, oid)
                print(f"[SL CANCEL] {symbol}:{position_side} orderId={oid} -> {resp}")
        except Exception as exc:
            print(f"[SL CANCEL] {symbol}:{position_side} {exc}")


def set_leverage_and_margin(symbol: str, leverage: int) -> None:
    try:
        resp = _signed_post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
        print("[LEVERAGE]", symbol, resp.status_code, resp.text)
    except Exception as exc:
        print(f"[WARN] leverage set failed {symbol}: {exc}")
    try:
        resp = _signed_post("/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})
        print("[MARGIN]", symbol, resp.status_code, resp.text)
    except Exception as exc:
        print(f"[WARN] marginType set failed {symbol}: {exc}")


def get_price(symbol: str) -> Decimal:
    resp = http_session.get(f"{BASE_URL}/fapi/v1/ticker/price", params={"symbol": symbol}, timeout=5)
    resp.raise_for_status()
    return _decimal(resp.json()["price"])


def get_daily_realized_pnl() -> Decimal:
    try:
        resp = _signed_get("/fapi/v2/account", {})
        payload = resp.json()
        pnl = _decimal(payload.get("totalRealizedProfit", "0"))
        print(f"[PnL] totalRealizedProfit={pnl}")
        return pnl
    except Exception as exc:
        print(f"[PnL ERROR] {exc}")
        return Decimal("0")


# ------------------------------------------------------------------------------
# Order utilities
# ------------------------------------------------------------------------------

def place_futures_market_order(symbol: str, side: str, quantity: Decimal, position_side: str, leverage: int) -> Dict[str, Any]:
    precision = PrecisionCache.get(symbol)
    adj_qty = _floor_quantity(symbol, quantity, precision)
    if adj_qty <= 0:
        raise RuntimeError(f"quantity<=0 for {symbol}")
    qty_str = _format_quantity(symbol, adj_qty, precision)
    set_leverage_and_margin(symbol, leverage)
    payload = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": qty_str,
        "positionSide": position_side,
    }
    print(f"[ORDER PREP] {symbol} qty={qty_str} precision={precision}")
    resp = _signed_post("/fapi/v1/order", payload)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    print(f"[ORDER] {symbol} -> {data}")
    if resp.status_code != 200:
        if isinstance(data, dict) and data.get("code") == -1111:
            print(f"[PRECISION ERROR] {symbol} payload={payload} resp={data}")
        raise RuntimeError(f"order failed: {resp.status_code} {data}")
    return data


def _close_position_market(symbol: str, position_side: str, qty: Decimal) -> None:
    if qty <= 0:
        return
    precision = PrecisionCache.get(symbol)
    adj_qty = _floor_quantity(symbol, qty, precision)
    if adj_qty <= 0:
        print(f"[CLOSE] {symbol}:{position_side} qty<=0 skip (raw={qty})")
        return
    qty_str = _format_quantity(symbol, adj_qty, precision)
    payload = {
        "symbol": symbol,
        "side": "SELL" if position_side.upper() == "LONG" else "BUY",
        "type": "MARKET",
        "quantity": qty_str,
        "positionSide": position_side.upper(),
        "reduceOnly": True,
    }
    try:
        resp = _signed_post("/fapi/v1/order", payload)
        print(f"[CLOSE] {symbol}:{position_side} qty={qty_str} resp={resp.text}")
    except Exception as exc:
        print(f"[CLOSE ERROR] {symbol}:{position_side} {exc}")


def place_stop_loss_close(symbol: str, stop_price: Decimal, position_side: str) -> Dict[str, Any]:
    precision = PrecisionCache.get(symbol)
    stop_str = _format_price(symbol, stop_price, position_side, precision)
    cancel_existing_sl_orders(symbol, position_side.upper())
    payload = {
        "symbol": symbol,
        "side": "SELL" if position_side.upper() == "LONG" else "BUY",
        "type": "STOP_MARKET",
        "stopPrice": stop_str,
        "closePosition": True,
        "priceProtect": True,
        "positionSide": position_side.upper(),
        "workingType": "MARK_PRICE",
    }
    print(f"[SL PREP] {symbol}:{position_side} stop={stop_str}")
    resp = _signed_post("/fapi/v1/order", payload)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    print(f"[SL] {symbol}:{position_side} -> {data}")
    if resp.status_code != 200:
        if isinstance(data, dict) and data.get("code") == -1111:
            print(f"[PRECISION ERROR] SL {symbol} payload={payload} resp={data}")
        raise RuntimeError(f"stop order failed: {resp.status_code} {data}")
    return data


# ------------------------------------------------------------------------------
# PnL helpers & quantity
# ------------------------------------------------------------------------------

def _compute_pnl(entry: Decimal, mark: Decimal, qty: Decimal, side: str) -> Decimal:
    if side.upper() == "BUY":
        return (mark - entry) * qty
    return (entry - mark) * qty


def _roe_from_pnl(pnl: Decimal, margin: Decimal) -> Decimal:
    """
    PnL (USDT) -> ROE% dönüşümü.
    margin <= 0 ise 0 döner (bölme hatasını önlemek için).
    """
    if margin <= 0:
        return Decimal("0")
    return (pnl / margin) * Decimal("100")


def _pnl_from_roe(roe_percent: Decimal, margin: Decimal) -> Decimal:
    """
    ROE% -> PnL (USDT) dönüşümü.
    """
    return (roe_percent / Decimal("100")) * margin


def _position_margin(state: Dict[str, Any]) -> Decimal:
    """
    Şimdilik, pozisyon başına kullanılan margin'i BOT_MARGIN_USDT olarak varsay.
    """
    try:
        return _decimal(state.get("margin", BOT_MARGIN_USDT))
    except Exception:
        return BOT_MARGIN_USDT


def _target_sl_roe_from_peak(peak_roe: Decimal) -> Decimal:
    """
    Basit ROI merdiveni:
    - Başlangıç SL: INITIAL_SL_ROE
    - Her +5% peak ROE artışı SL'yi +5 ROE yukarı taşır
    - Formül: floor(peak_roe / 5) * 5 + INITIAL_SL_ROE (alt sınır INITIAL_SL_ROE)
    """
    step = Decimal("5")
    initial_sl_roe = INITIAL_SL_ROE

    if peak_roe <= Decimal("0"):
        return initial_sl_roe

    steps = (peak_roe // step)
    sl_roe = steps * step + initial_sl_roe

    if sl_roe < initial_sl_roe:
        sl_roe = initial_sl_roe

    return sl_roe


def _target_sl_pnl_from_peak(peak: Decimal) -> Optional[Decimal]:
    if peak < Decimal("1"):
        return None
    if peak < Decimal("5"):
        return Decimal("0")
    steps = (peak // Decimal("5"))
    return steps * Decimal("1")


def _sl_price_from_target_pnl(entry: Decimal, qty: Decimal, side: str, target_pnl: Decimal) -> Decimal:
    if qty <= 0:
        return entry
    if side.upper() == "BUY":
        return entry + (target_pnl / qty)
    return entry - (target_pnl / qty)


def compute_quantity(symbol: str, entry_price: Decimal, leverage: int) -> Decimal:
    entry = _decimal(entry_price)
    if entry <= 0:
        raise ValueError("entry must be > 0")
    notional = BOT_MARGIN_USDT * Decimal(leverage)
    raw_qty = notional / entry
    precision = PrecisionCache.get(symbol)
    qty = _floor_quantity(symbol, raw_qty, precision)
    if qty <= 0:
        raise RuntimeError("calculated quantity <= 0")
    return qty


def simulate_roi_trailing(
    entry_price: Decimal,
    direction: str,
    margin: Decimal,
    leverage: int,
    prices: list[Decimal],
) -> list[Dict[str, Any]]:
    """
    Offline simulation of ROI tabanlı trailing davranışı.
    """
    side = "BUY" if direction.upper() == "LONG" else "SELL"
    entry = _decimal(entry_price)
    m = _decimal(margin)
    lev = Decimal(leverage)

    notional = m * lev
    qty = notional / entry if entry > 0 else Decimal("0")
    if qty <= 0:
        raise ValueError("simulate_roi_trailing: qty calculated <= 0")

    results: list[Dict[str, Any]] = []

    initial_sl_roe = INITIAL_SL_ROE
    initial_target_pnl = _pnl_from_roe(initial_sl_roe, m)
    sl_price = _sl_price_from_target_pnl(entry, qty, side, initial_target_pnl)
    sl_roe = initial_sl_roe

    peak_pnl = Decimal("0")
    peak_roe = Decimal("0")

    for idx, p in enumerate(prices):
        price = _decimal(p)
        pnl = _compute_pnl(entry, price, qty, side)
        roe = _roe_from_pnl(pnl, m)

        peak_pnl = max(peak_pnl, pnl)
        peak_roe = max(peak_roe, roe)

        target_roe = _target_sl_roe_from_peak(peak_roe)
        note = "SL unchanged"

        target_pnl = _pnl_from_roe(target_roe, m)
        candidate_sl_price = _sl_price_from_target_pnl(entry, qty, side, target_pnl)
        should_move = (
            sl_price == 0
            or (direction.upper() == "LONG" and candidate_sl_price > sl_price)
            or (direction.upper() == "SHORT" and candidate_sl_price < sl_price)
        )
        if should_move:
            sl_price = candidate_sl_price
            sl_roe = target_roe
            note = "SL moved"

        results.append(
            {
                "step": idx,
                "price": float(price),
                "pnl": float(pnl),
                "roe": float(roe),
                "peak_roe": float(peak_roe),
                "sl_roe": float(sl_roe),
                "sl_price": float(sl_price),
                "note": note,
            }
        )

    return results


# ------------------------------------------------------------------------------
# Watcher thread
# ------------------------------------------------------------------------------

def roi_watcher(state_key: str) -> None:
    time.sleep(2)
    while True:
        with state_lock:
            state = open_positions.get(state_key)
        if not state:
            return

        symbol = state["symbol"]
        side = state["side"]
        position_side = state["position_side"]
        entry_price: Decimal = state["entry"]
        current_sl: Decimal = state.get("sl", Decimal("0"))
        peak_pnl: Decimal = state.get("peak_pnl", Decimal("0"))
        peak_roe: Decimal = _decimal(state.get("peak_roe", "0"))
        margin: Decimal = _position_margin(state)

        try:
            pos = get_position_risk(symbol, position_side)
        except Exception as exc:
            print(f"[WATCHER] {state_key} positionRisk error {exc}")
            time.sleep(WATCH_INTERVAL_SECONDS)
            continue

        position_amt = _decimal(pos.get("positionAmt", "0"))
        abs_amt = abs(position_amt)

        if abs_amt <= Decimal("0"):
            print(f"[WATCHER] {state_key} position closed")
            with state_lock:
                open_positions.pop(state_key, None)
                watcher_threads.pop(state_key, None)
            return

        try:
            mark_price = _decimal(pos.get("markPrice", get_price(symbol)))
        except Exception:
            mark_price = entry_price

        pnl = _compute_pnl(entry_price, mark_price, abs_amt, side)
        roe_now = _roe_from_pnl(pnl, margin)

        peak_pnl = max(peak_pnl, pnl)
        peak_roe = max(peak_roe, roe_now)

        target_roe = _target_sl_roe_from_peak(peak_roe)
        target_pnl = _pnl_from_roe(target_roe, margin)
        target_price = _sl_price_from_target_pnl(entry_price, abs_amt, side, target_pnl)
        stop_str = _format_price(symbol, target_price, position_side)
        stop_price = _decimal(stop_str)

        should_move = (
            current_sl == 0
            or (position_side == "LONG" and stop_price > current_sl)
            or (position_side == "SHORT" and stop_price < current_sl)
        )

        if should_move:
            print(
                f"[SL TRAIL] {state_key} pnl={pnl:.2f} roe={roe_now:.2f}% "
                f"peak_roe={peak_roe:.2f}% target_roe={target_roe}% stop={stop_str}"
            )
            try:
                place_stop_loss_close(symbol, stop_price, position_side)
                with state_lock:
                    state["sl"] = stop_price
                    state["sl_roe"] = target_roe
                    state["peak_pnl"] = peak_pnl
                    state["peak_roe"] = peak_roe
                current_sl = stop_price
            except Exception as exc:
                print(f"[SL ERROR] {state_key} {exc}")
                with state_lock:
                    state["peak_pnl"] = peak_pnl
                    state["peak_roe"] = peak_roe
        else:
            with state_lock:
                state["peak_pnl"] = peak_pnl
                state["peak_roe"] = peak_roe

        time.sleep(WATCH_INTERVAL_SECONDS)


# ------------------------------------------------------------------------------
# Webhook endpoint
# ------------------------------------------------------------------------------

@app.route("/webhook", methods=["POST"])
def webhook() -> Any:
    if DAILY_MAX_LOSS < 0:
        pnl = get_daily_realized_pnl()
        if pnl <= DAILY_MAX_LOSS:
            return jsonify({"status": "blocked", "reason": "DAILY_MAX_LOSS", "pnl": float(pnl)}), 403

    data = request.get_json(force=True, silent=True) or {}
    try:
        raw_symbol = str(data["ticker"]).replace("/", "").split(".")[0].upper()
        symbol = SYMBOL_ALIASES.get(raw_symbol, raw_symbol)
        direction = str(data["dir"]).upper()
        entry = _decimal(data["entry"])
    except Exception:
        return jsonify({"status": "error", "msg": "invalid payload", "data": data}), 400

    if direction not in ("LONG", "SHORT"):
        return jsonify({"status": "error", "msg": "invalid direction"}), 400

    side = "BUY" if direction == "LONG" else "SELL"
    position_side = "LONG" if direction == "LONG" else "SHORT"

    try:
        qty = compute_quantity(symbol, entry, DEFAULT_LEVERAGE)
    except Exception as exc:
        return jsonify({"status": "error", "msg": f"quantity error: {exc}"}), 400

    current_long = get_position_risk(symbol, "LONG")
    current_short = get_position_risk(symbol, "SHORT")
    amt_long = abs(_decimal(current_long.get("positionAmt", "0")))
    amt_short = abs(_decimal(current_short.get("positionAmt", "0")))

    if (position_side == "LONG" and amt_long > 0) or (position_side == "SHORT" and amt_short > 0):
        print(f"[ALARM IGNORE] {symbol} {position_side} already open")
        return jsonify({"status": "ignored", "reason": "same_direction_exists"}), 200

    if position_side == "LONG" and amt_short > 0:
        _close_position_market(symbol, "SHORT", amt_short)
    elif position_side == "SHORT" and amt_long > 0:
        _close_position_market(symbol, "LONG", amt_long)

    try:
        order_res = place_futures_market_order(symbol, side, qty, position_side, DEFAULT_LEVERAGE)
    except Exception as exc:
        return jsonify({"status": "error", "msg": f"order error: {exc}"}), 500

    raw_avg = _decimal(order_res.get("avgPrice", "0"))
    if raw_avg > 0:
        entry_price = raw_avg
    else:
        try:
            pos_after = get_position_risk(symbol, position_side)
            entry_price = _decimal(pos_after.get("entryPrice", entry))
            if entry_price <= 0:
                entry_price = entry
        except Exception:
            entry_price = entry

    # --- INITIAL ROI-BASED STOP LOSS ---
    position_margin = BOT_MARGIN_USDT
    initial_sl_roe = INITIAL_SL_ROE
    initial_target_pnl = _pnl_from_roe(initial_sl_roe, position_margin)
    sl_for_state = Decimal("0")
    sl_roe_for_state = initial_sl_roe

    try:
        initial_sl_price = _sl_price_from_target_pnl(entry_price, qty, side, initial_target_pnl)
        place_stop_loss_close(symbol, initial_sl_price, position_side)
        sl_for_state = initial_sl_price
        print(f"[INIT SL] {symbol}:{position_side} roe={initial_sl_roe}% price={initial_sl_price}")
    except Exception as exc:
        print(f"[INIT SL ERROR] {symbol}:{position_side} {exc}")
        sl_for_state = Decimal("0")

    state_key = f"{symbol}:{position_side}"
    with state_lock:
        open_positions[state_key] = {
            "symbol": symbol,
            "entry": entry_price,
            "qty": qty,
            "side": side,
            "position_side": position_side,
            "leverage": DEFAULT_LEVERAGE,
            "sl": sl_for_state,
            "peak_pnl": Decimal("0"),
            "margin": position_margin,
            "sl_roe": sl_roe_for_state,
            "peak_roe": Decimal("0"),
            "opened_at": datetime.now().isoformat(),
        }
        watcher = watcher_threads.get(state_key)
        if not watcher or not watcher.is_alive():
            t = threading.Thread(target=roi_watcher, args=(state_key,), daemon=True)
            watcher_threads[state_key] = t
            t.start()

    return jsonify(
        {
            "status": "ok",
            "symbol": symbol,
            "direction": direction,
            "entry": float(entry_price),
            "qty": float(qty),
            "leverage": DEFAULT_LEVERAGE,
            "order": order_res,
        }
    )


# ------------------------------------------------------------------------------
# Dashboard & API endpoints
# ------------------------------------------------------------------------------


@app.route("/", methods=["GET"])
def dashboard() -> Any:
    return render_template("index.html")


@app.route("/api/status", methods=["GET"])
@login_required
def api_status() -> Any:
    config = {
        "DEFAULT_LEVERAGE": DEFAULT_LEVERAGE,
        "BOT_MARGIN_USDT": float(BOT_MARGIN_USDT),
        "DAILY_MAX_LOSS": float(DAILY_MAX_LOSS),
        "INITIAL_SL_ROE": float(INITIAL_SL_ROE),
        "USE_DYNAMIC_PRECISION": USE_DYNAMIC_PRECISION,
        "WATCH_INTERVAL_SECONDS": WATCH_INTERVAL_SECONDS,
    }
    return jsonify({"bot_version": BOT_VERSION, "health": "running", "config": _to_serializable(config)})


@app.route("/api/open-positions", methods=["GET"])
@login_required
def api_open_positions() -> Any:
    snapshot = _snapshot_positions()
    positions: List[Dict[str, Any]] = []
    for state_key, state in snapshot.items():
        try:
            entry = float(_decimal(state.get("entry", "0")))
        except Exception:
            entry = 0.0
        try:
            qty = float(_decimal(state.get("qty", "0")))
        except Exception:
            qty = 0.0
        try:
            sl_price = float(_decimal(state.get("sl", "0")))
        except Exception:
            sl_price = 0.0
        try:
            sl_roe = float(_decimal(state.get("sl_roe", "0")))
        except Exception:
            sl_roe = 0.0
        try:
            peak_roe = float(_decimal(state.get("peak_roe", "0")))
        except Exception:
            peak_roe = 0.0
        try:
            peak_pnl = float(_decimal(state.get("peak_pnl", "0")))
        except Exception:
            peak_pnl = 0.0
        try:
            margin = float(_decimal(state.get("margin", BOT_MARGIN_USDT)))
        except Exception:
            margin = float(BOT_MARGIN_USDT)

        positions.append(
            _to_serializable(
                {
                    "state_key": state_key,
                    "symbol": state.get("symbol"),
                    "side": state.get("side"),
                    "position_side": state.get("position_side"),
                    "entry": entry,
                    "qty": qty,
                    "sl": sl_price,
                    "sl_roe": sl_roe,
                    "peak_roe": peak_roe,
                    "peak_pnl": peak_pnl,
                    "leverage": state.get("leverage", DEFAULT_LEVERAGE),
                    "margin": margin,
                    "opened_at": state.get("opened_at", ""),
                }
            )
        )

    return jsonify({"positions": positions})


@app.route("/api/simulate-roi-trailing", methods=["POST"])
@login_required
def api_simulate_roi_trailing() -> Any:
    payload = request.get_json(force=True, silent=True) or {}
    try:
        entry_price = _decimal(payload["entry_price"])
        direction = str(payload["direction"]).upper()
        margin = _decimal(payload.get("margin", BOT_MARGIN_USDT))
        leverage = int(payload.get("leverage", DEFAULT_LEVERAGE))
        prices_raw = payload["prices"]
    except Exception:
        return jsonify({"status": "error", "message": "Eksik veya hatalı alanlar"}), 400

    if direction not in ("LONG", "SHORT"):
        return jsonify({"status": "error", "message": "Yön LONG veya SHORT olmalı"}), 400
    if margin <= 0:
        return jsonify({"status": "error", "message": "Margin 0'dan büyük olmalı"}), 400
    if leverage <= 0:
        return jsonify({"status": "error", "message": "Kaldıraç 0'dan büyük olmalı"}), 400
    if not isinstance(prices_raw, list) or not prices_raw:
        return jsonify({"status": "error", "message": "Geçerli fiyat listesi gerekli"}), 400

    try:
        price_list: List[Decimal] = [_decimal(p) for p in prices_raw]
    except Exception:
        return jsonify({"status": "error", "message": "Fiyat listesi sayısal olmalı"}), 400

    try:
        results = simulate_roi_trailing(entry_price, direction, margin, leverage, price_list)
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({"status": "ok", "steps": results})


# ------------------------------------------------------------------------------
# Auth endpoints
# ------------------------------------------------------------------------------


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login() -> Any:
    """Login endpoint."""
    data = request.get_json(force=True, silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password required"}), 400
    user = find_user(username)
    if not user or not check_password_hash(user.get("password_hash", ""), password):
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401
    session["user"] = {"username": user["username"], "role": user.get("role", "trader")}
    logger.info(f"User logged in: {username}")
    return jsonify({"status": "ok", "user": {"username": user["username"], "role": user.get("role", "trader")}})


@app.route("/api/auth/logout", methods=["POST"])
@login_required
def api_auth_logout() -> Any:
    """Logout endpoint."""
    username = session.get("user", {}).get("username", "unknown")
    session.clear()
    logger.info(f"User logged out: {username}")
    return jsonify({"status": "ok"})


@app.route("/api/auth/me", methods=["GET"])
@login_required
def api_auth_me() -> Any:
    """Get current user info."""
    return jsonify({"status": "ok", "user": session.get("user")})


# ------------------------------------------------------------------------------
# Config endpoints
# ------------------------------------------------------------------------------


@app.route("/api/config", methods=["GET"])
@login_required
def api_config_get() -> Any:
    """Get current config."""
    config = load_config()
    return jsonify({"status": "ok", "config": config})


@app.route("/api/config", methods=["POST"])
@login_required
def api_config_post() -> Any:
    """Update config."""
    data = request.get_json(force=True, silent=True) or {}
    current = load_config()
    current.update(data)
    # Validate types
    try:
        current["BOT_MARGIN_USDT"] = float(current.get("BOT_MARGIN_USDT", 5))
        current["BOT_LEVERAGE"] = int(current.get("BOT_LEVERAGE", 20))
        current["BOT_DAILY_MAX_LOSS"] = float(current.get("BOT_DAILY_MAX_LOSS", -100))
        current["BOT_INITIAL_SL_ROE"] = float(current.get("BOT_INITIAL_SL_ROE", -20))
        current["BOT_WATCH_INTERVAL_SECONDS"] = float(current.get("BOT_WATCH_INTERVAL_SECONDS", 3))
        current["USE_DYNAMIC_PRECISION"] = bool(current.get("USE_DYNAMIC_PRECISION", True))
        current["TEST_MODE"] = bool(current.get("TEST_MODE", False))
        current["AUTO_LOGOUT_MINUTES"] = int(current.get("AUTO_LOGOUT_MINUTES", 30))
    except Exception as exc:
        return jsonify({"status": "error", "message": f"Invalid config values: {exc}"}), 400
    save_config(current)
    apply_config(current)
    logger.info("Config updated")
    return jsonify({"status": "ok", "config": current})


@app.route("/api/config/reset", methods=["POST"])
@login_required
def api_config_reset() -> Any:
    """Reset config to defaults."""
    default_config = {
        "BOT_MARGIN_USDT": 5.0,
        "BOT_LEVERAGE": 20,
        "BOT_DAILY_MAX_LOSS": -100.0,
        "BOT_INITIAL_SL_ROE": -20.0,
        "BOT_WATCH_INTERVAL_SECONDS": 3.0,
        "USE_DYNAMIC_PRECISION": True,
        "TEST_MODE": False,
        "AUTO_LOGOUT_MINUTES": 30,
    }
    save_config(default_config)
    apply_config(default_config)
    logger.info("Config reset to defaults")
    return jsonify({"status": "ok", "config": default_config})


# ------------------------------------------------------------------------------
# User management endpoints
# ------------------------------------------------------------------------------


@app.route("/api/users", methods=["GET"])
@admin_required
def api_users_get() -> Any:
    """Get all users (admin only)."""
    users = load_users()
    safe_users = []
    for user in users:
        safe_users.append(
            {
                "username": user["username"],
                "role": user.get("role", "trader"),
                "api_key": mask_api_key(user.get("api_key", "")),
                "theme_preference": user.get("theme_preference", "dark"),
            }
        )
    return jsonify({"status": "ok", "users": safe_users})


@app.route("/api/users", methods=["POST"])
@admin_required
def api_users_post() -> Any:
    """Create new user (admin only)."""
    data = request.get_json(force=True, silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    role = data.get("role", "trader").strip()
    api_key = data.get("api_key", "").strip()
    api_secret = data.get("api_secret", "").strip()
    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password required"}), 400
    if role not in ("admin", "trader"):
        return jsonify({"status": "error", "message": "Role must be admin or trader"}), 400
    if not create_user(username, password, role, api_key, api_secret):
        return jsonify({"status": "error", "message": "Username already exists"}), 400
    return jsonify({"status": "ok", "message": "User created"})


@app.route("/api/users/<username>", methods=["DELETE"])
@admin_required
def api_users_delete(username: str) -> Any:
    """Delete user (admin only)."""
    users = load_users()
    filtered = [u for u in users if u.get("username") != username]
    if len(filtered) == len(users):
        return jsonify({"status": "error", "message": "User not found"}), 404
    save_users(filtered)
    logger.info(f"User deleted: {username}")
    return jsonify({"status": "ok", "message": "User deleted"})


@app.route("/api/users/<username>/reset-password", methods=["POST"])
@admin_required
def api_users_reset_password(username: str) -> Any:
    """Reset user password (admin only)."""
    data = request.get_json(force=True, silent=True) or {}
    new_password = data.get("password", "").strip()
    if not new_password:
        return jsonify({"status": "error", "message": "Password required"}), 400
    users = load_users()
    found = False
    for user in users:
        if user.get("username") == username:
            user["password_hash"] = generate_password_hash(new_password)
            found = True
            break
    if not found:
        return jsonify({"status": "error", "message": "User not found"}), 404
    save_users(users)
    logger.info(f"Password reset for: {username}")
    return jsonify({"status": "ok", "message": "Password reset", "new_password": new_password})


# ------------------------------------------------------------------------------
# PnL summary endpoint
# ------------------------------------------------------------------------------


@app.route("/api/pnl/summary", methods=["GET"])
@login_required
def api_pnl_summary() -> Any:
    """Get PnL summary (daily, total, ROI)."""
    try:
        daily_pnl = get_daily_realized_pnl()
        # For total, we'd need to track historical PnL. For now, use daily as placeholder.
        total_pnl = daily_pnl  # TODO: Implement proper total tracking
        # Calculate overall ROI (simplified: assume initial margin * number of trades)
        # This is a placeholder - real implementation would track total margin used
        overall_roi = 0.0
        if BOT_MARGIN_USDT > 0:
            # Rough estimate: daily_pnl / margin
            overall_roi = float((daily_pnl / BOT_MARGIN_USDT) * Decimal("100"))
        return jsonify(
            {
                "status": "ok",
                "daily_realized_pnl": float(daily_pnl),
                "total_realized_pnl": float(total_pnl),
                "overall_roi": overall_roi,
            }
        )
    except Exception as exc:
        logger.error(f"PnL summary error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


# ------------------------------------------------------------------------------
# Position close endpoint
# ------------------------------------------------------------------------------


@app.route("/api/position/close", methods=["POST"])
@login_required
def api_position_close() -> Any:
    """Close a position by state_key."""
    data = request.get_json(force=True, silent=True) or {}
    state_key = data.get("state_key", "").strip()
    if not state_key:
        return jsonify({"status": "error", "message": "state_key required"}), 400
    with state_lock:
        state = open_positions.get(state_key)
        if not state:
            return jsonify({"status": "error", "message": "Position not found"}), 404
        symbol = state.get("symbol")
        position_side = state.get("position_side")
        qty = _decimal(state.get("qty", "0"))
    try:
        _close_position_market(symbol, position_side, qty)
        logger.info(f"Position closed via API: {state_key}")
        return jsonify({"status": "ok", "message": "Position close order placed"})
    except Exception as exc:
        logger.error(f"Position close error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


# ------------------------------------------------------------------------------
# Logs endpoint
# ------------------------------------------------------------------------------


@app.route("/api/logs", methods=["GET"])
@login_required
def api_logs() -> Any:
    """Get recent log lines."""
    limit = int(request.args.get("limit", 200))
    log_file = LOGS_DIR / "bot.log"
    if not log_file.exists():
        return jsonify({"status": "ok", "logs": []})
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            recent = lines[-limit:] if len(lines) > limit else lines
            return jsonify({"status": "ok", "logs": [line.strip() for line in recent]})
    except Exception as exc:
        logger.error(f"Logs read error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


# ------------------------------------------------------------------------------
# BTC Strategy Summary endpoint
# ------------------------------------------------------------------------------


@app.route("/api/btc-strategy-summary", methods=["GET"])
@login_required
def api_btc_strategy_summary() -> Any:
    """Get BTC strategy summary (dummy data for now)."""
    # TODO: Implement real BTC strategy logic
    dummy_data = {
        "symbol": "BTCUSDT",
        "long_trend": True,
        "last_long_start_price": 62350.0,
        "current_price": 64120.0,
        "breakout_price": 65500.0,
        "confidence_score": 73,
    }
    return jsonify({"status": "ok", **dummy_data})


# ------------------------------------------------------------------------------
# Health check endpoint
# ------------------------------------------------------------------------------


@app.route("/api/health", methods=["GET"])
def api_health() -> Any:
    """Public health check endpoint (no auth required)."""
    try:
        # Simple health check - just verify app is running
        return jsonify({"status": "ok", "health": "running", "bot_version": BOT_VERSION})
    except Exception:
        return jsonify({"status": "error", "health": "degraded"}), 500


# ------------------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)



