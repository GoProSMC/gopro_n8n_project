#!/usr/bin/env python3
"""
Analyze CLI - Trigger n8n Analyzer workflow for any stock symbol or company name

Usage:
    python analyze.py TSLA.US
    python analyze.py AAPL.US --lookback 30
    python analyze.py MSFT.US --model models/gemini-2.0-flash-exp
    python analyze.py "Apple" --market US
"""

import argparse
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

# Configuration
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "http://localhost:5678")
WEBHOOK_PATH = "webhook/analyze"


def lookup_symbol_by_name(name, *, count=5):
    """
    Resolve a company name to a ticker using Yahoo Finance's public search API.
    Returns the raw symbol from the API (no market suffix added).
    """
    url = "https://query1.finance.yahoo.com/v1/finance/search"
    params = {"q": name, "quotesCount": count, "newsCount": 0}
    resp = requests.get(
        url,
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json() or {}
    quotes = data.get("quotes") or []
    candidate = next(
        (q for q in quotes if (q.get("quoteType") or "").lower() == "equity" and q.get("symbol")),
        None,
    )
    if not candidate and quotes:
        candidate = quotes[0]
    return (candidate.get("symbol") or "").strip().upper() if candidate else ""


def resolve_symbol(query, default_market_suffix="US"):
    """
    Accepts either a ticker or a company name and returns a Stooq-friendly ticker.
    - If the input already looks like a ticker with a market suffix (e.g. AAPL.US), it is returned in uppercase.
    - Otherwise we try to resolve the name via Yahoo search and append the provided market suffix when missing.
    """
    value = (query or "").strip()
    if not value:
        raise ValueError("A symbol or company name is required.")

    if "." in value:
        return value.upper()

    symbol = ""
    try:
        symbol = lookup_symbol_by_name(value)
    except Exception as exc:  # noqa: BLE001
        # Fall back to user input if lookup fails
        print(f"[warn] Symbol lookup failed for '{value}': {exc}")

    final_symbol = (symbol or value).upper()
    if "." not in final_symbol and default_market_suffix:
        final_symbol = f"{final_symbol}.{default_market_suffix.upper()}"
    return final_symbol


def trigger_analysis(symbol, lookback=60, model="models/gemini-2.5-flash"):
    """Trigger the n8n Analyzer workflow via webhook"""

    webhook_url = f"{N8N_BASE_URL}/{WEBHOOK_PATH}"

    payload = {
        "symbol": symbol,
        "lookback": lookback,
        "model": model,
    }

    print(f"[>] Analyzing {symbol}...")
    print(f"    Lookback: {lookback} days")
    print(f"    Model: {model}")
    print(f"    Webhook: {webhook_url}")
    print()

    try:
        response = requests.post(webhook_url, json=payload, timeout=120)

        if response.status_code == 200:
            print("[ok] Analysis complete!")
            print()

            # Try to parse response
            try:
                result = response.json()
                if isinstance(result, dict):
                    print("[info] Results:")
                    print(f"    Symbol: {result.get('symbol', 'N/A')}")
                    print(f"    Date: {result.get('date', 'N/A')}")
                    print(f"    Signal: {result.get('value', 'N/A')}")
                    print(f"    Confidence: {result.get('threshold', 'N/A')}")
                    print(f"    Message: {result.get('message', 'N/A')}")
                else:
                    print(f"Response: {result}")
            except Exception:
                print(f"Response (raw): {response.text[:500]}")

            print()
            print("[info] Results saved to: data/signals.xlsx")
            return True

        print(f"[err] HTTP {response.status_code}")
        print(f"    {response.text}")
        return False

    except requests.exceptions.Timeout:
        print("[warn] Request timeout (analysis may still be running in background)")
        print("       Check n8n execution logs or signals.xlsx for results")
        return False

    except requests.exceptions.ConnectionError:
        print("[err] Connection error: Could not reach n8n")
        print(f"      Make sure n8n is running at {N8N_BASE_URL}")
        return False

    except Exception as exc:  # noqa: BLE001
        print(f"[err] Unexpected error: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a stock by ticker or company name using Gemini AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyze.py TSLA.US
  python analyze.py AAPL.US --lookback 30
  python analyze.py "Apple Inc" --market US
  python analyze.py "Tesla" --model models/gemini-2.0-flash-exp
        """,
    )

    parser.add_argument(
        "query",
        type=str,
        help="Stock symbol or company name to analyze (e.g., AAPL.US or Apple)",
    )

    parser.add_argument(
        "--lookback",
        type=int,
        default=60,
        help="Number of days to look back (default: 60)",
    )

    parser.add_argument(
        "--model",
        type=str,
        default="models/gemini-2.5-flash",
        help="Gemini model to use (default: models/gemini-2.5-flash)",
    )

    parser.add_argument(
        "--market",
        type=str,
        default="US",
        help="Market suffix to append when lookup returns a bare ticker (default: US -> .US)",
    )

    args = parser.parse_args()

    if not args.query or len(args.query.strip()) < 1:
        print("[err] A symbol or company name is required.")
        sys.exit(1)

    try:
        symbol = resolve_symbol(args.query, default_market_suffix=args.market)
    except ValueError as exc:
        print(f"[err] {exc}")
        sys.exit(1)

    if symbol != args.query.upper():
        print(f"[info] Resolved '{args.query}' -> {symbol}")
    else:
        print(f"[info] Using symbol: {symbol}")

    success = trigger_analysis(
        symbol=symbol,
        lookback=args.lookback,
        model=args.model,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
