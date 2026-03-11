from typing import Optional
"""
바이낸스 USD-M 선물 클라이언트 (ccxt 기반)

역할:
  - API 연결 / 인증
  - 잔고 / 포지션 / 캔들 조회
  - 심볼별 레버리지 & 격리마진 설정
  - 시장가 / 지정가 / 스탑 주문 실행

설계 원칙:
  - 모든 예외는 여기서 잡아 로깅 후 None / False 반환
  - 상위 레이어는 None 체크만 하면 됨
  - 멀티 심볼: 심볼을 인자로 받아 동적으로 처리
"""
import logging
import math

import ccxt

from config.settings import get_api_credentials
from config.constants import LEVERAGE

logger = logging.getLogger(__name__)


def create_client() -> ccxt.binanceusdm:
    """인증된 Binance USD-M 선물 클라이언트 생성"""
    creds = get_api_credentials()
    return ccxt.binanceusdm({
        "apiKey":          creds["api_key"],
        "secret":          creds["api_secret"],
        "enableRateLimit": True,
        "options":         {"adjustForTimeDifference": True},
    })


def check_connection(exchange: ccxt.binanceusdm) -> bool:
    """API 연결 및 선물 권한 확인"""
    try:
        exchange.fetch_balance({"type": "future"})
        logger.info("[연결] 바이낸스 선물 API 연결 성공")
        return True
    except ccxt.AuthenticationError:
        logger.error("[연결] API Key 인증 실패 — .env 확인 필요")
        return False
    except Exception as e:
        logger.error(f"[연결] 연결 오류: {e}")
        return False


def setup_symbol(exchange: ccxt.binanceusdm, symbol: str) -> bool:
    """
    심볼 초기 설정: 격리 마진 + 레버리지 5x

    격리 마진: 포지션별 손실이 다른 포지션에 영향 없음 (멀티 포지션 운용 필수)
    """
    ccxt_sym = _to_ccxt(symbol)
    try:
        exchange.set_margin_mode("isolated", ccxt_sym)
    except ccxt.ExchangeError as e:
        # 이미 격리 마진인 경우 오류 무시
        if "already" not in str(e).lower() and "no need" not in str(e).lower():
            logger.warning(f"[설정] {symbol} 마진 모드 설정 실패: {e}")

    try:
        exchange.set_leverage(LEVERAGE, ccxt_sym)
        logger.info(f"[설정] {symbol} 격리마진 + {LEVERAGE}x 완료")
        return True
    except Exception as e:
        logger.error(f"[설정] {symbol} 레버리지 설정 실패: {e}")
        return False


def get_usdt_balance(exchange: ccxt.binanceusdm) -> float:
    """사용 가능한 USDT 잔고 (선물 지갑, 가용 증거금)"""
    try:
        bal = exchange.fetch_balance({"type": "future"})
        return float(bal["USDT"]["free"])
    except Exception as e:
        logger.error(f"[잔고] 조회 실패: {e}")
        return 0.0


def get_total_balance(exchange: ccxt.binanceusdm) -> float:
    """선물 지갑 총 잔고 (미실현 PnL 포함 — 일손실 기준용)"""
    try:
        bal = exchange.fetch_balance({"type": "future"})
        return float(bal["USDT"]["total"])
    except Exception as e:
        logger.error(f"[잔고] 총잔고 조회 실패: {e}")
        return 0.0


def fetch_ohlcv(exchange: ccxt.binanceusdm, symbol: str, limit: int = 30) -> list:
    """
    완성된 1시간봉 OHLCV 반환 (마지막 미완성 봉 제외)

    Returns
    -------
    [{"timestamp": ms, "open": f, "high": f, "low": f, "close": f, "volume": f}, ...]
    """
    try:
        raw = exchange.fetch_ohlcv(_to_ccxt(symbol), timeframe="1h", limit=limit + 1)
        if not raw or len(raw) < 2:
            return []
        # 마지막 봉은 현재 진행 중 → 제외
        return [
            {"timestamp": c[0], "open": c[1], "high": c[2],
             "low": c[3], "close": c[4], "volume": c[5]}
            for c in raw[:-1]
        ]
    except Exception as e:
        logger.error(f"[캔들] {symbol} 조회 실패: {e}")
        return []


def get_current_price(exchange: ccxt.binanceusdm, symbol: str) -> float:
    """현재 마크 가격 반환"""
    try:
        ticker = exchange.fetch_ticker(_to_ccxt(symbol))
        return float(ticker["last"])
    except Exception as e:
        logger.error(f"[가격] {symbol} 조회 실패: {e}")
        return 0.0


def get_position(exchange: ccxt.binanceusdm, symbol: str) -> Optional[dict]:
    """
    심볼 현재 포지션 반환

    Returns
    -------
    {"side": "long", "qty": float, "entry_price": float,
     "unrealized_pnl": float, "mark_price": float}
    포지션 없으면 None
    """
    try:
        positions = exchange.fetch_positions([_to_ccxt(symbol)])
        for pos in positions:
            qty = float(pos.get("contracts", 0) or 0)
            if qty > 0:
                return {
                    "side":           pos["side"],
                    "qty":            qty,
                    "entry_price":    float(pos.get("entryPrice", 0) or 0),
                    "unrealized_pnl": float(pos.get("unrealizedPnl", 0) or 0),
                    "mark_price":     float(pos.get("markPrice", 0) or 0),
                }
        return None
    except Exception as e:
        logger.error(f"[포지션] {symbol} 조회 실패: {e}")
        return None


def cancel_order(exchange: ccxt.binanceusdm, symbol: str, order_id: str) -> bool:
    """단일 주문 취소 (이미 체결/취소된 경우도 True 반환)"""
    try:
        exchange.cancel_order(order_id, _to_ccxt(symbol))
        return True
    except ccxt.OrderNotFound:
        return True   # 이미 처리된 주문 → 정상
    except Exception as e:
        logger.error(f"[취소] {symbol} order_id={order_id} 실패: {e}")
        return False


def cancel_all_orders(exchange: ccxt.binanceusdm, symbol: str) -> bool:
    """심볼의 모든 미체결 주문 일괄 취소"""
    try:
        exchange.cancel_all_orders(_to_ccxt(symbol))
        logger.info(f"[전체취소] {symbol} 완료")
        return True
    except Exception as e:
        logger.error(f"[전체취소] {symbol} 실패: {e}")
        return False


def place_market_order(exchange: ccxt.binanceusdm,
                       symbol: str,
                       side: str,
                       usdt_notional: float,
                       current_price: float,
                       reduce_only: bool = False) -> Optional[dict]:
    """
    시장가 주문

    Parameters
    ----------
    side          : "buy" (진입) | "sell" (청산)
    usdt_notional : 노셔널 금액 (USDT, 레버리지 적용된 포지션 크기)
    current_price : 수량 계산용 현재가
    reduce_only   : True = 포지션 감소 전용 (청산 시 사용)
    """
    try:
        ccxt_sym = _to_ccxt(symbol)
        qty = _calc_qty(exchange, ccxt_sym, usdt_notional, current_price)
        if qty <= 0:
            logger.warning(f"[시장가] {symbol} 수량 계산 실패 → 건너뜀")
            return None

        params = {"reduceOnly": reduce_only} if reduce_only else {}
        order = exchange.create_order(ccxt_sym, "market", side, qty, params=params)
        logger.info(
            f"[시장가] {symbol} {side.upper()} qty={qty} "
            f"notional=${usdt_notional:.0f} reduce_only={reduce_only}"
        )
        return order
    except Exception as e:
        logger.error(f"[시장가] {symbol} {side} 실패: {e}")
        return None


def place_stop_market(exchange: ccxt.binanceusdm,
                      symbol: str,
                      side: str,
                      stop_price: float,
                      qty: float) -> Optional[dict]:
    """
    스탑 마켓 주문 (손절용 — 거래소에 등록되어 봇 장애 시에도 SL 유지)

    Parameters
    ----------
    side       : "sell" (롱 손절)
    stop_price : 트리거 가격 (진입가 × (1 - SL_PCT))
    qty        : 전체 포지션 수량
    """
    try:
        order = exchange.create_order(
            _to_ccxt(symbol), "STOP_MARKET", side, qty,
            params={"stopPrice": stop_price, "reduceOnly": True}
        )
        logger.info(
            f"[스탑마켓] {symbol} {side.upper()} qty={qty} trigger=${stop_price:.4f}"
        )
        return order
    except Exception as e:
        logger.error(f"[스탑마켓] {symbol} 실패: {e}")
        return None


def place_limit_order(exchange: ccxt.binanceusdm,
                      symbol: str,
                      side: str,
                      price: float,
                      qty: float) -> Optional[dict]:
    """
    지정가 주문 (익절용 — GTC + reduceOnly)

    Parameters
    ----------
    side  : "sell" (롱 익절)
    price : 익절 가격
    qty   : 청산 수량 (TP1: 전체 × 50%, TP2: 나머지 50%)
    """
    try:
        order = exchange.create_order(
            _to_ccxt(symbol), "LIMIT", side, qty, price,
            params={"reduceOnly": True, "timeInForce": "GTC"}
        )
        logger.info(f"[지정가] {symbol} {side.upper()} qty={qty} @ ${price:.4f}")
        return order
    except Exception as e:
        logger.error(f"[지정가] {symbol} 실패: {e}")
        return None


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _to_ccxt(symbol: str) -> str:
    """"SOLUSDT" → "SOL/USDT:USDT" (ccxt USD-M 선물 심볼 형식)"""
    if "/" in symbol:
        return symbol
    base = symbol.replace("USDT", "")
    return f"{base}/USDT:USDT"


def _calc_qty(exchange: ccxt.binanceusdm,
              ccxt_sym: str,
              usdt_notional: float,
              price: float) -> float:
    """노셔널 금액과 현재가로 수량 계산, 심볼 정밀도에 맞게 내림 처리"""
    if price <= 0:
        return 0.0
    raw = usdt_notional / price
    try:
        exchange.load_markets()
        market    = exchange.market(ccxt_sym)
        precision = market["precision"]["amount"]
        if isinstance(precision, int):
            factor = 10 ** precision
            return math.floor(raw * factor) / factor
        else:
            # step size 방식 (ex: 0.001)
            return math.floor(raw / precision) * precision
    except Exception:
        return round(raw, 3)
