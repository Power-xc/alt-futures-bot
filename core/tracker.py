"""
포지션 트래커 - 오픈 포지션 상태 모니터링 및 청산 처리

매 사이클(60초)마다 실행:
  1. 시간손절 체크  - 진입 후 48h 경과 시 시장가 청산
  2. SL/TP 체결 확인 - 거래소 실제 포지션 vs 저장된 상태 비교
     - 포지션 소멸 = SL 또는 TP2 체결
     - 포지션 수량 50% 감소 = TP1 체결

SL/TP 주문은 거래소에 등록되어 있어 봇 다운 시에도 자동 체결됨
트래커는 체결 후 상태 동기화 및 알림 전송이 목적
"""
import logging
from datetime import datetime, timezone

import ccxt

from exchange.client import get_position, get_current_price
from exchange.order import close_position_market
from core.state import (
    remove_position, update_position, update_daily_pnl,
)
import notifications.telegram as tg

logger = logging.getLogger(__name__)


def check_all_positions(exchange: ccxt.binanceusdm, state: dict) -> None:
    """
    모든 오픈 포지션 상태 체크 및 청산 처리

    메인 루프에서 매 사이클마다 호출
    """
    # 포지션 목록 복사 (순회 중 수정 방지)
    positions = list(state["open_positions"])

    for pos in positions:
        symbol = pos["symbol"]
        try:
            _check_position(exchange, state, pos)
        except Exception as e:
            logger.error(f"[트래커] {symbol} 체크 중 오류: {e}")


def _check_position(exchange: ccxt.binanceusdm,
                    state: dict,
                    pos: dict) -> None:
    """단일 포지션 상태 체크"""
    symbol      = pos["symbol"]
    entry_time  = datetime.fromisoformat(pos["entry_time"])
    expiry_time = datetime.fromisoformat(pos["expiry_time"])
    now         = datetime.now(timezone.utc)

    # ── 1. 시간손절 (48h 초과) ────────────────────────────────────────────────
    if now >= expiry_time:
        logger.info(f"[트래커] {symbol} 48h 시간손절 -> 시장가 청산")
        _close_and_record(exchange, state, pos, reason="시간손절")
        return

    # ── 2. 거래소 실제 포지션 동기화 ─────────────────────────────────────────
    real_pos = get_position(exchange, symbol)

    if real_pos is None:
        # 포지션 소멸 = SL 또는 TP2 완전 체결
        _handle_position_closed(exchange, state, pos)
        return

    # TP1 체결 여부 확인: 수량이 초기의 ~50%로 줄었는지
    if not pos["tp1_hit"]:
        original_qty = pos["qty"]
        current_qty  = real_pos["qty"]
        # 수량 45% 이상 감소 = TP1 체결로 판단 (슬리피지 마진 포함)
        if current_qty < original_qty * 0.55:
            _handle_tp1_hit(exchange, state, pos, real_pos)


def _handle_tp1_hit(exchange: ccxt.binanceusdm,
                    state: dict,
                    pos: dict,
                    real_pos: dict) -> None:
    """TP1 체결 처리"""
    symbol     = pos["symbol"]
    tp1_price  = pos["tp1_price"]
    entry_price = pos["entry_price"]
    qty_closed  = pos["qty"] * 0.5
    pnl_est     = (tp1_price - entry_price) * qty_closed

    logger.info(
        f"[TP1체결] {symbol} @ ${tp1_price:.4f} "
        f"qty={qty_closed:.4f} pnl_est=${pnl_est:+.2f}"
    )

    update_position(state, symbol, {"tp1_hit": True})
    update_daily_pnl(state, pnl_est)
    tg.notify_tp1(symbol, entry_price, tp1_price, pnl_est)


def _handle_position_closed(exchange: ccxt.binanceusdm,
                             state: dict,
                             pos: dict) -> None:
    """포지션 완전 종료 처리 (SL 또는 TP2 체결)"""
    symbol      = pos["symbol"]
    entry_price = pos["entry_price"]
    tp1_hit     = pos["tp1_hit"]
    tp2_price   = pos["tp2_price"]
    sl_price    = pos["sl_price"]

    if tp1_hit:
        # TP1 이미 체결됨 -> TP2로 종료
        qty_closed = pos["qty"] * 0.5
        pnl_est    = (tp2_price - entry_price) * qty_closed
        reason     = "TP2"
        close_price = tp2_price
    else:
        # TP1 미체결 -> SL로 종료
        qty_closed  = pos["qty"]
        pnl_est     = (sl_price - entry_price) * qty_closed
        reason      = "SL"
        close_price = sl_price

    logger.info(
        f"[{reason}체결] {symbol} @ ${close_price:.4f} "
        f"pnl_est=${pnl_est:+.2f}"
    )

    update_daily_pnl(state, pnl_est)
    remove_position(state, symbol)

    tg.notify_close(
        symbol=symbol,
        entry_price=entry_price,
        exit_price=close_price,
        pnl=pnl_est,
        reason=reason,
    )


def _close_and_record(exchange: ccxt.binanceusdm,
                      state: dict,
                      pos: dict,
                      reason: str) -> None:
    """시장가 강제 청산 후 상태 업데이트"""
    symbol = pos["symbol"]
    success = close_position_market(exchange, symbol, reason=reason)

    if success:
        # 현재가 기준 PnL 추정 (실제 체결가는 거래소 확인 필요)
        current_price = get_current_price(exchange, symbol)
        pnl_est = (current_price - pos["entry_price"]) * pos["qty"]
        if pos["tp1_hit"]:
            pnl_est *= 0.5  # TP1 이미 청산된 수량 제외

        update_daily_pnl(state, pnl_est)
        remove_position(state, symbol)

        tg.notify_close(
            symbol=symbol,
            entry_price=pos["entry_price"],
            exit_price=current_price,
            pnl=pnl_est,
            reason=reason,
        )
