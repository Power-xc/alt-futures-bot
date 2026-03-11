from typing import Optional
"""
주문 실행 레이어 — 전략 로직을 실제 바이낸스 주문으로 변환

진입 플로우:
  1. 시장가 롱 진입 (노셔널 = 증거금 × 레버리지)
  2. 스탑 마켓 SL 등록  (진입가 × (1 - 0.07))
  3. 지정가 TP1 등록    (진입가 × (1 + 0.10), 50% 수량)
  4. 지정가 TP2 등록    (진입가 × (1 + 0.20), 나머지 50%)

청산 플로우:
  - TP1 체결 → SL 주문은 거래소에서 자동 부분 유지 (수량 감소)
  - TP2 체결 → 포지션 완전 종료
  - 시간손절 / 일손실 한도 → 모든 주문 취소 후 시장가 청산
"""
import logging

import ccxt

from exchange.client import (
    place_market_order, place_stop_market, place_limit_order,
    cancel_all_orders, get_position,
)
from config.constants import SL_PCT, TP1_PCT, TP2_PCT, TP1_CLOSE_RATIO

logger = logging.getLogger(__name__)


def enter_long(exchange: ccxt.binanceusdm,
               symbol: str,
               margin: float,
               notional: float,
               current_price: float) -> Optional[dict]:
    """
    롱 진입 + SL/TP 주문 일괄 등록

    Parameters
    ----------
    margin        : 증거금 (USDT) — equity × HALF_KELLY
    notional      : 노셔널 (USDT) — margin × LEVERAGE
    current_price : 진입 시점 현재가

    Returns
    -------
    {
      "entry_price": float,      # 진입가 (현재가 기준)
      "qty":         float,      # 체결 수량
      "sl_price":    float,      # SL 트리거 가격
      "tp1_price":   float,      # TP1 가격
      "tp2_price":   float,      # TP2 가격
      "sl_order_id": str,        # SL 주문 ID
      "tp1_order_id":str,        # TP1 주문 ID
      "tp2_order_id":str,        # TP2 주문 ID
    }
    실패 시 None
    """
    # ── 1. 시장가 진입 ────────────────────────────────────────
    entry_order = place_market_order(
        exchange, symbol, "buy", notional, current_price
    )
    if not entry_order:
        return None

    # 체결 수량 확인 (filled → 실제 체결량)
    qty         = float(entry_order.get("filled") or notional / current_price)
    entry_price = float(entry_order.get("average") or current_price)

    # ── 2. 가격 계산 ─────────────────────────────────────────
    sl_price  = round(entry_price * (1 - SL_PCT), 6)
    tp1_price = round(entry_price * (1 + TP1_PCT), 6)
    tp2_price = round(entry_price * (1 + TP2_PCT), 6)

    qty1 = round(qty * TP1_CLOSE_RATIO, 6)           # TP1: 50%
    qty2 = round(qty - qty1, 6)                       # TP2: 나머지 50%

    logger.info(
        f"[진입완료] {symbol} | 진입가=${entry_price:.4f} qty={qty:.4f} "
        f"| SL=${sl_price:.4f} TP1=${tp1_price:.4f} TP2=${tp2_price:.4f}"
    )

    # ── 3. SL 스탑 마켓 주문 등록 ────────────────────────────
    sl_order = place_stop_market(exchange, symbol, "sell", sl_price, qty)

    # ── 4. TP1 / TP2 지정가 주문 등록 ────────────────────────
    tp1_order = place_limit_order(exchange, symbol, "sell", tp1_price, qty1)
    tp2_order = place_limit_order(exchange, symbol, "sell", tp2_price, qty2)

    return {
        "entry_price":  entry_price,
        "qty":          qty,
        "sl_price":     sl_price,
        "tp1_price":    tp1_price,
        "tp2_price":    tp2_price,
        "sl_order_id":  str(sl_order["id"])  if sl_order  else "",
        "tp1_order_id": str(tp1_order["id"]) if tp1_order else "",
        "tp2_order_id": str(tp2_order["id"]) if tp2_order else "",
    }


def close_position_market(exchange: ccxt.binanceusdm,
                           symbol: str,
                           reason: str = "") -> bool:
    """
    포지션 전체 시장가 청산 (시간손절 / 일손실 한도 / 긴급 청산)

    1. 모든 미체결 주문(SL/TP) 취소
    2. 현재 포지션 수량 조회
    3. 시장가 sell (reduceOnly)
    """
    # 미체결 주문 전부 취소 (SL/TP 충돌 방지)
    cancel_all_orders(exchange, symbol)

    pos = get_position(exchange, symbol)
    if not pos:
        logger.info(f"[청산] {symbol} 포지션 없음 (이미 청산됨) reason={reason}")
        return True

    qty = pos["qty"]
    order = place_market_order(
        exchange, symbol, "sell",
        usdt_notional=qty * pos["mark_price"],
        current_price=pos["mark_price"],
        reduce_only=True,
    )
    if order:
        logger.info(f"[청산완료] {symbol} qty={qty} reason={reason}")
        return True

    logger.error(f"[청산실패] {symbol} reason={reason}")
    return False
