"""
🇳🇬 Nigerian On-Chain Tax Explainer
Data: Etherscan API (free, unlimited)
Classification: Nansen labeling taxonomy (DEX swap = taxable)
Tax engine: Nigeria PITA + NTA 2025 progressive bands
Built for Nansen Points Season 3 Community Showcase.
"""

import os
import datetime
import requests
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── Config ─────────────────────────────────────────────────────────────────────
ETHERSCAN_KEY  = os.environ.get("ETHERSCAN_API_KEY", "2NS4284PMNRUJIG8QW3Y8EMCGUPTECJY2P")
ETHERSCAN_BASE = "https://api.etherscan.io/v2/api"
EXCHANGE_URL   = "https://api.exchangerate-api.com/v4/latest/USD"

# ── Nigerian Tax Bands ─────────────────────────────────────────────────────────
BANDS_PITA = [
    {"label": "First ₦300,000",   "limit": 300_000,   "rate": 0.07},
    {"label": "Next ₦300,000",    "limit": 300_000,   "rate": 0.11},
    {"label": "Next ₦500,000",    "limit": 500_000,   "rate": 0.15},
    {"label": "Next ₦500,000",    "limit": 500_000,   "rate": 0.19},
    {"label": "Next ₦1,600,000",  "limit": 1_600_000, "rate": 0.21},
    {"label": "Above ₦3,200,000", "limit": None,      "rate": 0.24},
]

BANDS_NTA = [
    {"label": "₦0 – ₦800,000 (exempt)", "limit": 800_000,    "rate": 0.00},
    {"label": "₦800,001 – ₦3,000,000",  "limit": 2_200_000,  "rate": 0.15},
    {"label": "₦3M – ₦12,000,000",      "limit": 9_000_000,  "rate": 0.18},
    {"label": "₦12M – ₦25,000,000",     "limit": 13_000_000, "rate": 0.21},
    {"label": "₦25M – ₦50,000,000",     "limit": 25_000_000, "rate": 0.23},
    {"label": "Above ₦50,000,000",       "limit": None,       "rate": 0.25},
]

# ── Nansen DEX Taxonomy ────────────────────────────────────────────────────────
# Known DEX router addresses — same protocols Nansen labels as taxable swaps
DEX_ADDRESSES = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # Uniswap V2 Router
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # Uniswap V3 Router
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",  # Uniswap V3 Router 2
    "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b",  # Uniswap Universal Router
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad",  # Uniswap Universal Router 2
    "0x1111111254eeb25477b68fb85ed929f73a960582",  # 1inch V5
    "0x111111125421ca6dc452d289314280a0f8842a65",  # 1inch V6
    "0xdef171fe48cf0115b1d80b88dc8eab59176fee57",  # ParaSwap
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f",  # SushiSwap Router
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff",  # 0x / Matcha
    "0x9008d19f58aabd9ed0d60971565aa8510560ab41",  # CoW Protocol
    "0xba12222222228d8ba445958a75a0704d566bf2c8",  # Balancer Vault
    "0x99a58482bd75cbab83b27ec03ca68ff489b5788f",  # Curve Router
}

# Swap method signatures
SWAP_SELECTORS = {
    "0x38ed1739", "0x8803dbee", "0x7ff36ab5",
    "0x18cbafe5", "0x414bf389", "0xdb3e2198",
    "0xac9650d8", "0x5ae401dc", "0x04e45aaf",
    "0xb858183f", "0x12aa3caf",
}

# ── Core helpers ───────────────────────────────────────────────────────────────
def get_bands(date_to):
    return BANDS_NTA if date_to >= "2026-01-01" else BANDS_PITA

def get_regime(date_to):
    if date_to >= "2026-01-01":
        return {"label": "Nigeria Tax Act 2025 (NTA)", "note": "nta"}
    return {"label": "Personal Income Tax Act (PITA)", "note": "pita"}

def is_taxable(tx):
    to_addr    = (tx.get("to") or "").lower()
    func       = (tx.get("functionName") or "").lower()
    inp        = (tx.get("input") or "")[:10]
    if to_addr in DEX_ADDRESSES:
        return True
    if inp in SWAP_SELECTORS:
        return True
    swap_words = ["swap", "exchange", "exactinput", "exactoutput"]
    if any(w in func for w in swap_words):
        return True
    return False

def calc_tax(ngn_income, bands):
    remaining, total_tax, breakdown = ngn_income, 0.0, []
    for band in bands:
        if remaining <= 0:
            breakdown.append({**band, "slice": 0, "tax": 0})
            continue
        limit     = band["limit"] if band["limit"] is not None else remaining
        slice_amt = min(remaining, limit)
        tax       = slice_amt * band["rate"]
        remaining -= slice_amt
        total_tax += tax
        breakdown.append({**band, "slice": round(slice_amt, 2), "tax": round(tax, 2)})
    return {"total": round(total_tax, 2), "breakdown": breakdown}

def get_ngn_rate():
    try:
        r = requests.get(EXCHANGE_URL, timeout=8)
        return float(r.json()["rates"]["NGN"])
    except Exception:
        return 1620.0

def get_eth_price():
    try:
        r = requests.get(
            ETHERSCAN_BASE,
            params={"module": "stats", "action": "ethprice", "apikey": ETHERSCAN_KEY},
            timeout=8
        )
        d = r.json()
        if d.get("status") == "1":
            return float(d["result"]["ethusd"])
    except Exception:
        pass
    return 3200.0

def date_to_ts(date_str, end=False):
    d  = datetime.date.fromisoformat(date_str)
    dt = datetime.datetime(d.year, d.month, d.day, 23 if end else 0, 59 if end else 0, 59 if end else 0)
    return int(dt.timestamp())

def fetch_transactions(addr, date_from, date_to):
    ts_from = date_to_ts(date_from, end=False)
    ts_to   = date_to_ts(date_to,   end=True)
    all_txs = []

    for page in range(1, 6):
        try:
            r = requests.get(ETHERSCAN_BASE, params={
                "module":     "account",
                "action":     "txlist",
                "address":    addr,
                "startblock": 0,
                "endblock":   99999999,
                "page":       page,
                "offset":     200,
                "sort":       "desc",
                "apikey":     ETHERSCAN_KEY,
            }, timeout=20)

            data = r.json()
            if data.get("status") == "0":
                result = data.get("result", "")
                if not result or result == [] or "No transactions" in data.get("message",""):
                    break
                return [], str(result)

            txs = data.get("result", [])
            if not txs:
                break

            filtered = [tx for tx in txs if ts_from <= int(tx.get("timeStamp", 0)) <= ts_to]
            all_txs.extend(filtered)

            if txs and int(txs[-1].get("timeStamp", 0)) < ts_from:
                break
            if len(txs) < 200:
                break

        except requests.exceptions.Timeout:
            return all_txs, "Request timed out — try a shorter date range."
        except Exception as e:
            return all_txs, str(e)

    return all_txs, None

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/favicon.ico")
def favicon():
    return send_from_directory("static", "favicon.ico", mimetype="image/x-icon")

@app.route("/api/analyze", methods=["POST"])
def analyze():
    body      = request.json or {}
    addr      = (body.get("address")   or "").strip().lower()
    date_from = (body.get("date_from") or "").strip()
    date_to   = (body.get("date_to")   or "").strip()

    if not addr or not addr.startswith("0x") or len(addr) < 40:
        return jsonify({"error": "Invalid EVM address — must start with 0x, 42 characters."}), 400
    if not date_from or not date_to or date_from > date_to:
        return jsonify({"error": "Invalid date range — From must be before To."}), 400

    usd_ngn   = get_ngn_rate()
    eth_price = get_eth_price()
    regime    = get_regime(date_to)

    transactions, fetch_error = fetch_transactions(addr, date_from, date_to)

    if fetch_error and not transactions:
        return jsonify({"error": fetch_error}), 502

    if not transactions:
        return jsonify({"error":
            "No transactions found for this wallet in the selected period. "
            "Try a wider date range or verify the address."}), 404

    taxable_txs     = [tx for tx in transactions if is_taxable(tx)]
    non_taxable_txs = [tx for tx in transactions if not is_taxable(tx)]

    swap_vol_eth = sum(float(tx.get("value", 0)) / 1e18 for tx in taxable_txs)
    swap_vol_usd = swap_vol_eth * eth_price
    gain_usd     = swap_vol_usd * 0.15
    gain_ngn     = gain_usd * usd_ngn
    tax_result   = calc_tax(gain_ngn, get_bands(date_to))
    eff_rate     = (tax_result["total"] / gain_ngn * 100) if gain_ngn > 0 else 0.0

    def serialize(tx):
        ts    = int(tx.get("timeStamp", 0))
        func  = tx.get("functionName", "") or ""
        label = func.split("(")[0] if "(" in func else func
        label = label or ("dex swap" if is_taxable(tx) else "transfer")
        dt    = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else ""
        return {
            "date":       dt,
            "type":       label,
            "chain":      "ethereum",
            "hash":       tx.get("hash", ""),
            "taxable":    is_taxable(tx),
            "volume_usd": round(float(tx.get("value", 0)) / 1e18 * eth_price, 2),
        }

    return jsonify({
        "address":           addr,
        "date_from":         date_from,
        "date_to":           date_to,
        "usd_ngn":           round(usd_ngn, 2),
        "regime":            regime,
        "total_txns":        len(transactions),
        "taxable_count":     len(taxable_txs),
        "non_taxable_count": len(non_taxable_txs),
        "swap_vol_usd":      round(swap_vol_usd, 2),
        "gain_usd":          round(gain_usd, 2),
        "gain_ngn":          round(gain_ngn, 2),
        "gain_source":       "estimated",
        "tax_ngn":           tax_result["total"],
        "eff_rate":          round(eff_rate, 2),
        "tax_breakdown":     tax_result["breakdown"],
        "transactions":      [serialize(tx) for tx in transactions[:50]],
        "warning":           fetch_error,
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)
