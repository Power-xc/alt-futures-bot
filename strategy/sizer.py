"""
포지션 사이징 - Half Kelly x 레버리지

사이징 공식:
  margin   = equity x HALF_KELLY (11%)  <- 증거금 (실제 담보)
  notional = margin x LEVERAGE  (5x)    <- 노셔널 (포지션 크기)

  예시 (equity = $10,000):
    margin   = $1,100
    notional = $5,500
    최대 손실 (SL -7%) = $5,500 x 0.07 = $385 = 자본의 3.85%

Tier 1 한도 체크:
  notional > TIER1_LIMITS[symbol] -> 해당 신호 스킵
  레버리지를 낮추거나 조정하지 않음 (백테스팅과 동일하게 스킵)
"""
import logging

from config.constants import HALF_KELLY, LEVERAGE, TIER1_LIMITS

logger = logging.getLogger(__name__)


def calc_position_size(equity: float, symbol: str) -> tuple | None:
    """
    포지션 크기 계산 (Half Kelly x 5x)

    Parameters
    ----------
    equity : 현재 자본 (선물 지갑 총 잔고)
    symbol : "SOLUSDT" 형식

    Returns
    -------
    (margin, notional) 튜플
    Tier 1 한도 초과 시 None 반환

    Notes
    -----
    margin   : 실제 담보 금액 (증거금)
    notional : 포지션 노출 금액 (margin x leverage)
    """
    margin   = equity * HALF_KELLY
    notional = margin * LEVERAGE

    # Tier 1 노셔널 한도 체크
    tier1_limit = TIER1_LIMITS.get(symbol, 50_000)
    if notional > tier1_limit:
        logger.info(
            f"[사이징] {symbol} Tier1 한도 초과 -> 스킵 "
            f"(notional=${notional:,.0f} > limit=${tier1_limit:,})"
        )
        return None

    logger.info(
        f"[사이징] {symbol} margin=${margin:,.0f} "
        f"notional=${notional:,.0f} (Tier1 한도 ${tier1_limit:,})"
    )
    return margin, notional


def get_max_positions(equity: float) -> int:
    """
    자본 규모별 최대 동시 포지션 수

    소자본: 집중 투자 (3개) -> 대자본: 분산 (20개)
    자본 증가에 따라 자동 확장
    """
    from config.constants import MAX_POSITIONS_TABLE
    for threshold, max_pos in MAX_POSITIONS_TABLE:
        if equity < threshold:
            return max_pos
    return 20
