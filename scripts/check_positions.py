#!/usr/bin/env python3
"""
현재 오픈 포지션 및 봇 상태 확인 스크립트

사용법:
  python scripts/check_positions.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import datetime, timezone
from pathlib import Path

from exchange.client import create_client, check_connection, get_position, get_total_balance
from core.state import load_state


def main():
    print("\n" + "=" * 60)
    print("  봇 상태 및 포지션 현황")
    print("=" * 60)

    state = load_state()

    # 로컬 상태
    print(f"\n  [저장된 상태]")
    print(f"  오픈 포지션: {len(state['open_positions'])}개")
    print(f"  감시 중:     {len(state['pending_signals'])}개 심볼")
    ds = state["daily_state"]
    print(f"  오늘 날짜:   {ds['date']}")
    print(f"  오늘 PnL:    ${ds['realized_pnl']:+,.2f} ({ds['trade_count']}회)")
    print(f"  일 시작 자본: ${ds['equity_start']:,.0f}")

    exchange = create_client()
    if not check_connection(exchange):
        print("\n  API 연결 실패 - 거래소 조회 불가")
        sys.exit(1)

    equity = get_total_balance(exchange)
    print(f"\n  [거래소 잔고]")
    print(f"  총 자본: ${equity:,.2f}")

    print(f"\n  [오픈 포지션 상세]")
    if not state["open_positions"]:
        print("  없음")
    else:
        now = datetime.now(timezone.utc)
        for pos in state["open_positions"]:
            real = get_position(exchange, pos["symbol"])
            remaining_h = (datetime.fromisoformat(pos["expiry_time"]) - now).total_seconds() / 3600
            pnl_est = ((real["mark_price"] - pos["entry_price"]) * pos["qty"]) if real else 0
            print(
                f"\n  {pos['symbol']}"
                f"\n    진입가: ${pos['entry_price']:,.4f}  "
                f"SL: ${pos['sl_price']:,.4f}  "
                f"TP1: ${pos['tp1_price']:,.4f}  "
                f"TP2: ${pos['tp2_price']:,.4f}"
                f"\n    TP1체결: {'완료' if pos['tp1_hit'] else '대기'}  "
                f"만료까지: {remaining_h:.1f}h  "
                f"미실현PnL: ${pnl_est:+.2f}"
            )
    print()


if __name__ == "__main__":
    main()
