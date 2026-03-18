"""
🇳🇬 Nigerian On-Chain Tax Explainer
Users bring their own Nansen API key — each query uses their credits.
This drives Nansen credit consumption and ecosystem adoption.
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
NANSEN_BASE  = "https://api.nansen.ai/api/v1"
EXCHANGE_URL = "https://api.exchangerate-api.com/v4/latest/USD"

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
TAXABLE_KEYWORDS = [
    "dex", "swap", "uniswap", "sushiswap", "curve", "balancer",
    "pancakeswap", "1inch", "paraswap", "kyber", "dodo", "velodrome",
    "aerodrome", "odos", "camelot", "trader joe", "defi", "trade", "exchange"
]

# ── Helpers ────────────────────────────────────────────────────────────────────
def get_bands(date_to):
    return BANDS_NTA if date_to >= "2026-01-01" else BANDS_PITA

def get_regime(date_to):
    if date_to >= "2026-01-01":
        return {"label": "Nigeria Tax Act 2025 (NTA)", "note": "nta"}
    return {"label": "Personal Income Tax Act (PITA)", "note": "pita"}

def is_taxable(tx):
    haystack = " ".join(filter(None, [
        tx.get("transaction_type"), tx.get("transactionType"),
        tx.get("label"), tx.get("type"), tx.get("txType"),
        tx.get("action"), tx.get("protocol"), tx.get("dex_name"),
    ])).lower()
    return any(k in haystack for k in TAXABLE_KEYWORDS)

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

def fetch_nansen(addr, date_from, date_to, api_key):
    """Fetch transactions using the user's own Nansen API key."""
    headers = {"Content-Type": "application/json", "apikey": api_key}
    transactions = []
    error = None

    for page in range(1, 4):
        try:
            payload = {
                "address":         addr,
                "chain":           "ethereum",
                "hide_spam_token": True,
                "date": {
                    "from": date_from + "T00:00:00Z",
                    "to":   date_to   + "T23:59:59Z",
                },
                "pagination": {
                    "page":     page,
                    "per_page": 100,
                },
                "order_by": [{"field": "block_timestamp", "direction": "DESC"}],
            }
            resp = requests.post(
                f"{NANSEN_BASE}/profiler/address/transactions",
                json=payload,
                headers=headers,
                timeout=30,
            )

            if resp.status_code == 403:
                err = resp.json()
                if "credits" in str(err).lower():
                    return [], "insufficient_credits"
                return [], f"Nansen error: {resp.text[:200]}"

            if resp.status_code == 401:
                return [], "invalid_key"

            if not resp.ok:
                return [], f"Nansen {resp.status_code}: {resp.text[:200]}"

            data = resp.json()
            txs  = (data.get("data") or data.get("transactions") or
                    data.get("results") or (data if isinstance(data, list) else []))
            transactions.extend(txs)

            pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
            if len(txs) < 100 or pagination.get("is_last_page"):
                break

        except requests.exceptions.Timeout:
            return transactions, "timeout"
        except Exception as e:
            return transactions, str(e)

    return transactions, None

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
    addr      = (body.get("address")   or "").strip()
    date_from = (body.get("date_from") or "").strip()
    date_to   = (body.get("date_to")   or "").strip()
    api_key   = (body.get("api_key")   or "").strip()

    # Validate inputs
    if not api_key:
        return jsonify({"error": "Please enter your Nansen API key to continue."}), 400
    if not addr or not addr.startswith("0x") or len(addr) < 40:
        return jsonify({"error": "Invalid EVM address — must start with 0x, 42 characters."}), 400
    if not date_from or not date_to or date_from > date_to:
        return jsonify({"error": "Invalid date range — From must be before To."}), 400

    usd_ngn = get_ngn_rate()
    regime  = get_regime(date_to)

    # Fetch using user's key
    transactions, fetch_error = fetch_nansen(addr, date_from, date_to, api_key)

    # Handle specific errors with helpful messages
    if fetch_error == "invalid_key":
        return jsonify({"error":
            "Invalid Nansen API key. Check your key at nansen.ai/api and try again."}), 401

    if fetch_error == "insufficient_credits":
        return jsonify({"error":
            "Your Nansen API key has insufficient credits. "
            "Top up at nansen.ai/api to continue. Credits are valid for 1 year."}), 402

    if fetch_error == "timeout":
        return jsonify({"error":
            "Request timed out — try a shorter date range (3 months works best)."}), 504

    if fetch_error and not transactions:
        return jsonify({"error": fetch_error}), 502

    if not transactions:
        return jsonify({"error":
            "No transactions found for this wallet in the selected period. "
            "Try a wider date range or verify the address."}), 404

    # Classify using Nansen taxonomy
    taxable_txs     = [tx for tx in transactions if is_taxable(tx)]
    non_taxable_txs = [tx for tx in transactions if not is_taxable(tx)]

    # Calculate gain
    swap_vol_usd = sum(
        float(tx.get("volume_usd") or tx.get("volumeUsd") or
              tx.get("value_usd")  or tx.get("usd_value") or 0)
        for tx in taxable_txs
    )
    gain_usd     = swap_vol_usd * 0.15
    gain_ngn     = gain_usd * usd_ngn
    tax_result   = calc_tax(gain_ngn, get_bands(date_to))
    eff_rate     = (tax_result["total"] / gain_ngn * 100) if gain_ngn > 0 else 0.0

    def serialize(tx):
        return {
            "date":       tx.get("block_timestamp") or tx.get("timestamp") or "",
            "type":       (tx.get("transaction_type") or tx.get("transactionType") or
                           tx.get("label") or tx.get("type") or tx.get("action") or "transfer"),
            "chain":      tx.get("chain") or tx.get("blockchain") or "eth",
            "hash":       (tx.get("tx_hash") or tx.get("transaction_hash") or
                           tx.get("hash") or tx.get("txHash") or ""),
            "taxable":    is_taxable(tx),
            "volume_usd": float(tx.get("volume_usd") or tx.get("value_usd") or 0),
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
        "warning":           None,
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)
