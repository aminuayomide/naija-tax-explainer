# 🇳🇬 Naija Tax — Nigerian On-Chain Tax Explainer

The first Nigerian on-chain tax explainer. Paste an EVM wallet, get a
plain-English breakdown of your estimated tax liability under Nigeria's
progressive income bands — powered by Nansen's transaction labels.

Built for the **Nansen Points Season 3 Community Showcase**.

---

## Run Locally

```bash
pip install -r requirements.txt
python app.py
# → open http://localhost:5000
```

## Deploy to Render (get a public URL)

1. Push this folder to a GitHub repo
2. Go to https://render.com → New → Web Service
3. Connect your GitHub repo
4. Render auto-detects render.yaml — just set the NANSEN_API_KEY env variable
5. Click Deploy → you get a live public URL in ~2 minutes

---

## How It Works

```
Browser → Flask /api/analyze → Nansen (tx labels + PnL)
                              → ExchangeRate-API (USD/NGN)
       ← Tax engine (classify → calc → respond)
```

### Tax Classification
- Taxable: Nansen labels matching DEX/swap keywords (uniswap, curve, 1inch etc.)
- Non-taxable: transfers, bridges, approvals, other

### Gain Calculation
- If Nansen PnL summary is available → uses real realized PnL (shows "✓ Real PnL")
- Otherwise → 15% of total taxable swap volume (conservative estimate)

### Tax Regimes (auto-selected by date range)

**PITA — up to Dec 31 2025**
| Band | Rate |
|------|------|
| First ₦300,000 | 7% |
| Next ₦300,000 | 11% |
| Next ₦500,000 | 15% |
| Next ₦500,000 | 19% |
| Next ₦1,600,000 | 21% |
| Above ₦3,200,000 | 24% |

**NTA 2025 — from Jan 1 2026**
(Signed into law 26 June 2025. Source: KPMG Nigeria)
| Band | Rate |
|------|------|
| ₦0 – ₦800,000 | 0% (exempt) |
| ₦800,001 – ₦3,000,000 | 15% |
| ₦3M – ₦12,000,000 | 18% |
| ₦12M – ₦25,000,000 | 21% |
| ₦25M – ₦50,000,000 | 23% |
| Above ₦50,000,000 | 25% |

---

## Project Structure
```
naija-tax-v2/
├── app.py               # Flask backend + tax engine
├── requirements.txt     # Python dependencies
├── render.yaml          # Render deployment config
├── README.md
└── templates/
    └── index.html       # Full polished frontend
```

## V2 Ideas
- Historical NGN/USD rates per transaction
- Solana wallet support
- Multi-wallet aggregation
- Tax-loss harvesting suggestions (Nansen Token God Mode)
- FIRS-ready PDF with accountant signature fields
