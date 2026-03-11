"""
신호 스캐너 - 눌림목 롱 진입 신호 감지

신호 감지 로직:
  1단계 (급등 감지):
    - 24h 가격 변화율 >= +20% -> pump_high(24h 최고가) 기록, 감시 시작
    - 급등 감지 후 48h 이내에 눌림 미달 시 신호 자동 만료

  2단계 (눌림 확인):
    - 현재가 <= pump_high x (1 - 0.15) -> 진입 신호 발생

핵심: 즉각 추격 매수(승률 42~47%) 대신 눌림 대기(승률 65~70%)
"""
import logging
from datetime import datetime, timezone, timedelta

import ccxt

from exchange.client import fetch_ohlcv
from config.constants import (
    PUMP_THRESHOLD, PULLBACK_THRESHOLD, SIGNAL_EXPIRY_HOURS, CANDLE_LIMIT,
)

logger = logging.getLogger(__name__)


def scan_symbol(exchange: ccxt.binanceusdm,
                symbol: str,
                pending_signals: dict) -> dict | None:
    """
    단일 심볼 신호 스캔

    Parameters
    ----------
    exchange        : 바이낸스 클라이언트
    symbol          : "SOLUSDT" 형식
    pending_signals : 급등 감지 후 눌림 대기 중인 심볼 상태
                      { symbol: {"pump_high": float, "detected_at": datetime} }

    Returns
    -------
    진입 신호 발생 시:
      {"symbol": str, "entry_price": float, "pump_high": float, "pump_pct": float}
    신호 없으면 None

    Side Effect
    -----------
    pending_signals 딕셔너리를 직접 수정 (급등 감지/만료 처리)
    """
    candles = fetch_ohlcv(exchange, symbol, limit=CANDLE_LIMIT)
    if not candles or len(candles) < 25:
        return None

    now       = datetime.now(timezone.utc)
    close_now = candles[-1]["close"]

    # ── 1단계: 기존 감시 중인 심볼의 눌림 확인 ──────────────────────────────
    if symbol in pending_signals:
        info      = pending_signals[symbol]
        pump_high = info["pump_high"]
        detected  = info["detected_at"]
        pump_pct  = info["pump_pct"]

        # 감시 만료 확인 (48h 초과)
        if now - detected > timedelta(hours=SIGNAL_EXPIRY_HOURS):
            logger.debug(f"[만료] {symbol} 48h 경과 -> 신호 무효화")
            del pending_signals[symbol]
            return None

        # 눌림 조건: 현재가 <= 급등 고점 x (1 - 15%)
        pullback_target = pump_high * (1 - PULLBACK_THRESHOLD)
        if close_now <= pullback_target:
            logger.info(
                f"[신호] {symbol} 눌림 도달! "
                f"고점=${pump_high:.4f} -> 현재=${close_now:.4f} "
                f"({((close_now / pump_high) - 1) * 100:.1f}%) "
                f"원래 급등={pump_pct * 100:.1f}%"
            )
            del pending_signals[symbol]  # 신호 발생 -> 감시 목록 제거
            return {
                "symbol":      symbol,
                "entry_price": close_now,
                "pump_high":   pump_high,
                "pump_pct":    pump_pct,
            }
        return None  # 아직 눌림 미달

    # ── 2단계: 새로운 급등 감지 ─────────────────────────────────────────────
    # 24h = 24봉 전 종가 vs 현재 종가
    close_24h_ago = candles[-25]["close"]
    pump_pct      = (close_now - close_24h_ago) / close_24h_ago

    if pump_pct >= PUMP_THRESHOLD:
        # 24h 구간 최고가 = 눌림 기준 고점
        pump_high = max(c["high"] for c in candles[-25:])

        logger.info(
            f"[급등감지] {symbol} +{pump_pct * 100:.1f}% "
            f"고점=${pump_high:.4f} | 눌림 대기 시작"
        )
        pending_signals[symbol] = {
            "pump_high":   pump_high,
            "detected_at": now,
            "pump_pct":    pump_pct,
        }

    return None


def scan_all(exchange: ccxt.binanceusdm,
             symbols: list,
             pending_signals: dict,
             open_symbols: set) -> list:
    """
    전체 심볼 스캔 - 진입 신호 목록 반환

    Parameters
    ----------
    symbols         : 스캔 대상 심볼 리스트
    pending_signals : 급등 감지 후 눌림 대기 중인 상태 딕셔너리 (수정됨)
    open_symbols    : 현재 오픈 포지션이 있는 심볼 집합 (중복 진입 방지)

    Returns
    -------
    [{"symbol": str, "entry_price": float, "pump_high": float, "pump_pct": float}, ...]
    급등 폭 큰 순 정렬
    """
    signals = []

    for symbol in symbols:
        # 이미 포지션 있는 심볼 스킵 (중복 진입 방지)
        if symbol in open_symbols:
            continue

        try:
            sig = scan_symbol(exchange, symbol, pending_signals)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.warning(f"[스캔] {symbol} 오류 (건너뜀): {e}")

    # 급등 폭 큰 순 정렬 (우선순위 높은 신호 먼저)
    signals.sort(key=lambda s: s["pump_pct"], reverse=True)

    if signals:
        logger.info(f"[스캔완료] 진입 신호 {len(signals)}건: {[s['symbol'] for s in signals]}")
    else:
        logger.debug(f"[스캔완료] 신호 없음 (감시 중: {len(pending_signals)}개)")

    return signals
