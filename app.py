"""
🇳🇬 Nigerian On-Chain Tax Explainer
Flask backend — proxies Nansen API, runs tax engine, serves the UI.
Built for Nansen Points Season 3 Community Showcase.
"""

import os
import requests
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── Config ─────────────────────────────────────────────────────────────────────
NANSEN_KEY   = os.environ.get("NANSEN_API_KEY", "EGT5p6ea39tmtMelptLJ9y8daau3lKIG")
NANSEN_BASE  = "https://api.nansen.ai/api/beta"
EXCHANGE_URL = "https://api.exchangerate-api.com/v4/latest/USD"
HEADERS      = {"Content-Type": "application/json", "apikey": NANSEN_KEY}

# ── Tax Bands ──────────────────────────────────────────────────────────────────
# OLD: Personal Income Tax Act (PITA) — applies to tax years up to end of 2025
BANDS_PITA = [
    {"label": "First ₦300,000",    "limit": 300_000,   "rate": 0.07},
    {"label": "Next ₦300,000",     "limit": 300_000,   "rate": 0.11},
    {"label": "Next ₦500,000",     "limit": 500_000,   "rate": 0.15},
    {"label": "Next ₦500,000",     "limit": 500_000,   "rate": 0.19},
    {"label": "Next ₦1,600,000",   "limit": 1_600_000, "rate": 0.21},
    {"label": "Above ₦3,200,000",  "limit": None,      "rate": 0.24},
]

# NEW: Nigeria Tax Act 2025 (NTA) — effective January 1 2026
# Signed into law 26 June 2025. Source: KPMG Nigeria NTA analysis.
# Key changes: ₦800k full exemption, CGT merged into PIT, top rate 25%
BANDS_NTA = [
    {"label": "₦0 – ₦800,000",          "limit": 800_000,    "rate": 0.00},
    {"label": "₦800,001 – ₦3,000,000",  "limit": 2_200_000,  "rate": 0.15},
    {"label": "₦3M – ₦12,000,000",      "limit": 9_000_000,  "rate": 0.18},
    {"label": "₦12M – ₦25,000,000",     "limit": 13_000_000, "rate": 0.21},
    {"label": "₦25M – ₦50,000,000",     "limit": 25_000_000, "rate": 0.23},
    {"label": "Above ₦50,000,000",       "limit": None,       "rate": 0.25},
]

# Nansen label keywords → taxable DEX swap
TAXABLE_KEYWORDS = [
    "dex", "swap", "uniswap", "sushiswap", "curve", "balancer",
    "pancakeswap", "1inch", "paraswap", "kyber", "dodo", "velodrome",
    "aerodrome", "odos", "camelot", "trader joe", "defi", "trade", "exchange"
]

# ── Helpers ────────────────────────────────────────────────────────────────────
def get_bands(date_to: str):
    return BANDS_NTA if date_to >= "2026-01-01" else BANDS_PITA

def get_regime(date_to: str):
    if date_to >= "2026-01-01":
        return {"label": "Nigeria Tax Act 2025 (NTA)", "note": "nta"}
    return {"label": "Personal Income Tax Act (PITA)", "note": "pita"}

def is_taxable(tx: dict) -> bool:
    haystack = " ".join(filter(None, [
        tx.get("transaction_type"), tx.get("transactionType"),
        tx.get("label"), tx.get("type"), tx.get("txType"),
        tx.get("action"), tx.get("protocol"), tx.get("dex_name"),
    ])).lower()
    return any(k in haystack for k in TAXABLE_KEYWORDS)

def calc_tax(ngn_income: float, bands: list) -> dict:
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

def get_ngn_rate() -> float:
    try:
        r = requests.get(EXCHANGE_URL, timeout=8)
        return float(r.json()["rates"]["NGN"])
    except Exception:
        return 1620.0

def nansen_post(endpoint: str, payload: dict, timeout: int = 30):
    try:
        resp = requests.post(
            f"https://api.nansen.ai/api/beta/{endpoint}",
            json=payload,
            headers=HEADERS,
            timeout=timeout,
        )
        if not resp.ok:
            return None, f"Nansen {resp.status_code}: {resp.text[:300]}"
        return resp.json(), None
    except requests.exceptions.Timeout:
        return None, "timeout"
    except Exception as e:
        return None, f"Network error: {e}"

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

    if not addr or not addr.startswith("0x") or len(addr) < 40:
        return jsonify({"error": "Invalid EVM address — must start with 0x, 42 characters."}), 400
    if not date_from or not date_to or date_from > date_to:
        return jsonify({"error": "Invalid date range — From must be before To."}), 400

    usd_ngn = get_ngn_rate()
    regime  = get_regime(date_to)

    # ── Fetch transactions — FREE 0-credit endpoint ────────────────────────────
    # Source: docs.nansen.ai/nansen-api-reference
    # Cost: 0 credits (FREE, requires attribution)
    # Key: walletAddresses is an ARRAY, chain: "all", parameters wrapper
    transactions, nansen_error = [], None

    for page in range(1, 4):
        payload = {
            "parameters": {
                "walletAddresses": [addr],
                "chain":           "all",
                "hideSpamToken":   True,
            },
            "pagination": {
                "page":           page,
                "recordsPerPage": 100,
            },
            "filters": {
                "volumeUsd": {"from": 0.1},
                "blockTimestamp": {
                    "from": date_from + "T00:00:00.000Z",
                    "to":   date_to   + "T23:59:59.999Z",
                }
            }
        }
        data, err = nansen_post("profiler/address/transactions", payload, timeout=30)

        if err:
            nansen_error = err
            break

        # v1 wraps results in a top-level "data" array
        txs = (data.get("data") or
               data.get("transactions") or
               (data if isinstance(data, list) else []))
        transactions.extend(txs)

        pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
        if len(txs) < 100 or pagination.get("is_last_page"):
            break

    if nansen_error and not transactions:
        if '403' in str(nansen_error) or '401' in str(nansen_error):
            return jsonify({"error":
                "Nansen API credits required to fetch live data. "
                "This app is built and ready — add Nansen API credits to your account to activate live wallet analysis."}), 402
        if nansen_error == "timeout":
            return jsonify({"error":
                "Nansen timed out. Try a shorter date range — 3 months works best."}), 504
        return jsonify({"error": nansen_error}), 502

    if not transactions:
        return jsonify({"error":
            "No on-chain activity found for this wallet in the selected period. "
            "Try a wider date range or verify the address."}), 404

    # ── Classify ───────────────────────────────────────────────────────────────
    taxable_txs     = [tx for tx in transactions if is_taxable(tx)]
    non_taxable_txs = [tx for tx in transactions if not is_taxable(tx)]

    # ── Gain estimate: 15% of taxable swap volume (conservative) ──────────────
    # Note: we use the free transactions endpoint only (no PnL credits needed).
    # volume_usd on each tx is the total swap size; 15% is a conservative
    # net-gain assumption. Users are clearly shown this is an estimate.
    swap_vol_usd = sum(
        float(tx.get("volume_usd") or tx.get("volumeUsd") or
              tx.get("value_usd")  or tx.get("usd_value") or 0)
        for tx in taxable_txs
    )
    gain_usd = swap_vol_usd * 0.15

    gain_ngn     = gain_usd * usd_ngn
    active_bands = get_bands(date_to)
    tax_result   = calc_tax(gain_ngn, active_bands)
    eff_rate     = (tax_result["total"] / gain_ngn * 100) if gain_ngn > 0 else 0.0

    # ── Serialize top 50 txns for the UI table ─────────────────────────────────
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
        "warning":           nansen_error if nansen_error not in (None, "timeout") else None,
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)
