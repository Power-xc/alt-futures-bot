"""
리스크 관리 - 진입 전 3단계 필터

순서:
  1. 일손실 한도 체크  - 당일 손실이 시작 자본의 10% 초과 시 신규 진입 금지
  2. 동시 포지션 한도  - 자본 규모별 최대 포지션 수 초과 시 스킵
  3. Tier 1 노셔널 한도 - strategy/sizer.py 에서 처리 (calc_position_size 반환값)

하나라도 통과 못하면 해당 신호 스킵 (손절/강제청산 아님)
"""
import logging

import ccxt

from exchange.client import get_total_balance
from strategy.sizer import get_max_positions
from config.constants import DAILY_LOSS_LIMIT

logger = logging.getLogger(__name__)


def check_daily_loss(state: dict, equity: float) -> bool:
    """
    일손실 한도 체크

    Returns True (진입 가능) / False (오늘 진입 금지)

    로직:
      equity_start: 하루 첫 사이클에 기록한 시작 자본
      realized_pnl: 당일 실현 손익 합계
      한도: equity_start * DAILY_LOSS_LIMIT (10%)
    """
    ds = state["daily_state"]

    # 하루 시작 자본이 아직 기록 안 됐으면 현재 자본으로 초기화
    if ds["equity_start"] <= 0:
        ds["equity_start"] = equity
        logger.info(f"[리스크] 일 시작 자본 설정: ${equity:,.0f}")

    realized = ds["realized_pnl"]
    limit     = ds["equity_start"] * DAILY_LOSS_LIMIT

    if realized < -limit:
        logger.warning(
            f"[리스크] 일손실 한도 초과 -> 오늘 신규 진입 금지 "
            f"(손실 ${realized:+,.0f} / 한도 -${limit:,.0f})"
        )
        return False

    return True


def check_position_limit(state: dict, equity: float) -> bool:
    """
    동시 포지션 한도 체크

    Returns True (진입 가능) / False (포지션 수 초과)
    """
    current = len(state["open_positions"])
    maximum = get_max_positions(equity)

    if current >= maximum:
        logger.info(
            f"[리스크] 동시 포지션 한도 -> 스킵 "
            f"(현재 {current}개 / 최대 {maximum}개, 자본 ${equity:,.0f})"
        )
        return False

    return True


def can_enter(state: dict, equity: float) -> bool:
    """
    일손실 + 동시 포지션 한도 통합 체크

    Tier 1 한도는 calc_position_size() 에서 별도 처리

    Returns True = 진입 가능 / False = 이번 신호 스킵
    """
    if not check_daily_loss(state, equity):
        return False
    if not check_position_limit(state, equity):
        return False
    return True
