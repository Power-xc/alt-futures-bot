#!/usr/bin/env python3
"""
현재 시장에서 급등/눌림 신호 확인 스크립트 (실거래 없이 조회만)

사용법:
  python scripts/check_signals.py

출력:
  - 현재 급등 중인 심볼 목록
  - 눌림 대기 중인 심볼 (가상으로 24h 전부터 감시했다면)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exchange.client import create_client, check_connection, fetch_ohlcv
from config.constants import SCAN_SYMBOLS, PUMP_THRESHOLD, PULLBACK_THRESHOLD, CANDLE_LIMIT


def main():
    print("\n" + "=" * 60)
    print("  알트코인 신호 현황 조회")
    print("=" * 60)

    exchange = create_client()
    if not check_connection(exchange):
        print("API 연결 실패")
        sys.exit(1)

    pumping   = []  # 현재 급등 중
    pullback  = []  # 급등 후 눌림 진입 가능 구간

    for symbol in SCAN_SYMBOLS:
        try:
            candles = fetch_ohlcv(exchange, symbol, limit=CANDLE_LIMIT)
            if not candles or len(candles) < 25:
                continue

            close_now     = candles[-1]["close"]
            close_24h_ago = candles[-25]["close"]
            pump_pct      = (close_now - close_24h_ago) / close_24h_ago
            pump_high     = max(c["high"] for c in candles[-25:])
            pullback_pct  = (close_now / pump_high - 1) * 100

            if pump_pct >= PUMP_THRESHOLD:
                pumping.append({
                    "symbol":       symbol,
                    "pump_pct":     pump_pct * 100,
                    "pullback_pct": pullback_pct,
                    "price":        close_now,
                })

                # 이미 눌림 구간 도달 여부 체크
                if close_now <= pump_high * (1 - PULLBACK_THRESHOLD):
                    pullback.append(symbol)

        except Exception as e:
            print(f"  {symbol}: 오류 ({e})")

    print(f"\n  급등 심볼 (+{PUMP_THRESHOLD*100:.0f}% 이상): {len(pumping)}개")
    for s in sorted(pumping, key=lambda x: x["pump_pct"], reverse=True):
        tag = " ← 진입 가능!" if s["symbol"] in pullback else ""
        print(f"    {s['symbol']:12s}  +{s['pump_pct']:.1f}%  현재 고점대비 {s['pullback_pct']:+.1f}%{tag}")

    print(f"\n  눌림 진입 가능 심볼: {pullback}")
    print()


if __name__ == "__main__":
    main()
