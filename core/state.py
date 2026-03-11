"""
영속 상태 관리 - JSON 파일 기반

저장 데이터:
  - open_positions : 현재 오픈 포지션 목록
  - daily_state    : 일손실 추적 (당일 기준)
  - pending_signals: 급등 감지 후 눌림 대기 중인 심볼 상태

봇 재시작 시 상태 복원해서 연속성 유지
(SL/TP는 거래소에 주문으로 등록되어 있어 봇 다운 시에도 안전)
"""
import json
import logging
from datetime import datetime, timezone, date
from pathlib import Path

from config.constants import STATE_FILE

logger = logging.getLogger(__name__)

_STATE_PATH = Path(STATE_FILE)


def load_state() -> dict:
    """
    저장된 상태 로드

    Returns
    -------
    {
      "open_positions": [...],   # 오픈 포지션 목록
      "daily_state": {...},      # 일손실 추적
      "pending_signals": {...},  # 눌림 대기 신호
    }
    파일 없으면 빈 초기 상태 반환
    """
    if not _STATE_PATH.exists():
        return _empty_state()

    try:
        with _STATE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # pending_signals의 detected_at 문자열을 datetime으로 복원
        for sym, info in data.get("pending_signals", {}).items():
            if isinstance(info.get("detected_at"), str):
                info["detected_at"] = datetime.fromisoformat(info["detected_at"])

        # 날짜가 오늘이 아니면 daily_state 초기화
        saved_date = data.get("daily_state", {}).get("date", "")
        if saved_date != str(date.today()):
            data["daily_state"] = _empty_daily_state()
            logger.info("[상태] 날짜 변경 -> daily_state 초기화")

        logger.info(
            f"[상태] 로드 완료 | 포지션 {len(data['open_positions'])}개 "
            f"| 감시 중 {len(data['pending_signals'])}개"
        )
        return data

    except Exception as e:
        logger.error(f"[상태] 로드 실패 (초기화): {e}")
        return _empty_state()


def save_state(state: dict) -> None:
    """현재 상태를 JSON 파일에 저장"""
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        serializable = json.loads(json.dumps(state, default=_serialize))
        with _STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[상태] 저장 실패: {e}")


def add_position(state: dict, position: dict) -> None:
    """
    포지션 추가

    position 구조:
    {
      "symbol":       str,
      "entry_price":  float,
      "entry_time":   str (ISO 8601 UTC),
      "expiry_time":  str (ISO 8601 UTC),
      "qty":          float,
      "margin":       float,
      "notional":     float,
      "sl_price":     float,
      "tp1_price":    float,
      "tp2_price":    float,
      "tp1_hit":      bool,
      "sl_order_id":  str,
      "tp1_order_id": str,
      "tp2_order_id": str,
    }
    """
    state["open_positions"].append(position)
    save_state(state)
    logger.info(f"[상태] {position['symbol']} 포지션 추가 (총 {len(state['open_positions'])}개)")


def remove_position(state: dict, symbol: str) -> None:
    """심볼 포지션 제거"""
    before = len(state["open_positions"])
    state["open_positions"] = [
        p for p in state["open_positions"] if p["symbol"] != symbol
    ]
    if len(state["open_positions"]) != before:
        save_state(state)
        logger.info(f"[상태] {symbol} 포지션 제거 (총 {len(state['open_positions'])}개)")


def get_position_state(state: dict, symbol: str) -> dict | None:
    """심볼 포지션 상태 반환 (없으면 None)"""
    for p in state["open_positions"]:
        if p["symbol"] == symbol:
            return p
    return None


def update_position(state: dict, symbol: str, updates: dict) -> None:
    """포지션 필드 업데이트 (tp1_hit 등)"""
    for p in state["open_positions"]:
        if p["symbol"] == symbol:
            p.update(updates)
            save_state(state)
            return


def update_daily_pnl(state: dict, pnl: float) -> None:
    """당일 누적 PnL 업데이트"""
    state["daily_state"]["realized_pnl"] += pnl
    state["daily_state"]["trade_count"]  += 1
    save_state(state)


def get_open_symbols(state: dict) -> set:
    """현재 오픈 포지션 심볼 집합 반환"""
    return {p["symbol"] for p in state["open_positions"]}


# -- 내부 헬퍼 ----------------------------------------------------------------

def _empty_state() -> dict:
    return {
        "open_positions":  [],
        "daily_state":     _empty_daily_state(),
        "pending_signals": {},
    }


def _empty_daily_state() -> dict:
    return {
        "date":         str(date.today()),
        "realized_pnl": 0.0,
        "trade_count":  0,
        "equity_start": 0.0,  # 하루 시작 자본 (일손실 한도 기준)
    }


def _serialize(obj):
    """JSON 직렬화 불가 타입 변환"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return str(obj)
    raise TypeError(f"직렬화 불가: {type(obj)}")
