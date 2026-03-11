#!/usr/bin/env python3
"""
알트코인 눌림목 롱 전략 - 라이브 트레이딩

사용법:
  # 드라이런 (주문 없이 신호만 확인 - 처음 시작 시 필수)
  python run_live.py --dry-run

  # 실거래
  python run_live.py

시작 전 체크리스트:
  1. .env 파일 생성 (.env.example 참고)
  2. 바이낸스 서브계정 API Key/Secret 입력 (선물 거래 권한 필수)
  3. python run_live.py --dry-run 으로 신호 확인
  4. 선물 지갑에 USDT 입금 확인

동작 구조:
  - 매 60초마다: 오픈 포지션 상태 체크 (SL/TP 체결, 48h 만료)
  - 매 1시간봉 마감 직후: 전체 심볼 스캔 (급등/눌림 신호)
  - 매일 09:00 KST: 텔레그램 현황 보고
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timezone, timedelta

import ccxt

from exchange.client import create_client, check_connection, get_total_balance, get_usdt_balance, setup_symbol
from exchange.order import enter_long
from strategy.scanner import scan_all
from strategy.sizer import calc_position_size
from core.risk import can_enter
from core.tracker import check_all_positions
from core.state import (
    load_state, save_state, add_position,
    get_open_symbols,
)
import notifications.telegram as tg
from config.constants import (
    SCAN_SYMBOLS, SCAN_INTERVAL_SEC, CANDLE_SEC,
    DAILY_REPORT_HOUR, TIME_STOP_HOURS,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _next_candle_close_sec() -> int:
    """다음 1시간봉 마감까지 남은 초"""
    now = int(time.time())
    return (now // CANDLE_SEC + 1) * CANDLE_SEC - now


def _is_candle_hour(last_scan_hour: int) -> bool:
    """현재 시각이 마지막 스캔과 다른 시(hour)인지 확인"""
    return datetime.now(timezone.utc).hour != last_scan_hour


def _send_morning_report(state: dict, equity: float) -> None:
    """매일 09:00 KST 텔레그램 현황 보고"""
    ds = state["daily_state"]
    tg.notify_morning_report(
        equity=equity,
        open_positions=state["open_positions"],
        daily_pnl=ds["realized_pnl"],
        trade_count=ds["trade_count"],
        watching=len(state["pending_signals"]),
    )


def _execute_entry(exchange: ccxt.binanceusdm,
                   state: dict,
                   signal: dict,
                   equity: float,
                   dry_run: bool) -> None:
    """
    신호에 대한 진입 실행

    리스크 체크 -> 사이징 -> 주문 실행 -> 상태 저장 순으로 처리
    """
    symbol      = signal["symbol"]
    entry_price = signal["entry_price"]

    # ── 리스크 체크 (일손실 + 동시 포지션 한도) ──────────────────────────────
    if not can_enter(state, equity):
        return

    # ── 포지션 사이징 (Half Kelly x 5x, Tier1 체크) ──────────────────────────
    sizing = calc_position_size(equity, symbol)
    if sizing is None:
        return  # Tier1 한도 초과 -> 스킵
    margin, notional = sizing

    logger.info(
        f"[진입] {symbol} | 진입가=${entry_price:,.4f} "
        f"| 증거금=${margin:,.0f} | 노셔널=${notional:,.0f}"
    )

    if dry_run:
        logger.info(f"[DRY RUN] {symbol} 진입 건너뜀")
        return

    # ── 심볼 초기 설정 (격리마진 + 레버리지 5x) ──────────────────────────────
    # 진입 직전에 호출 (이미 설정돼 있어도 안전하게 덮어씀)
    setup_symbol(exchange, symbol)

    # ── 주문 실행 (시장가 + SL/TP 주문 일괄 등록) ────────────────────────────
    result = enter_long(exchange, symbol, margin, notional, entry_price)
    if not result:
        logger.error(f"[진입] {symbol} 주문 실패")
        return

    # ── 포지션 상태 저장 ──────────────────────────────────────────────────────
    now         = datetime.now(timezone.utc)
    expiry_time = now + timedelta(hours=TIME_STOP_HOURS)

    position = {
        "symbol":       symbol,
        "entry_price":  result["entry_price"],
        "entry_time":   now.isoformat(),
        "expiry_time":  expiry_time.isoformat(),
        "qty":          result["qty"],
        "margin":       margin,
        "notional":     notional,
        "sl_price":     result["sl_price"],
        "tp1_price":    result["tp1_price"],
        "tp2_price":    result["tp2_price"],
        "tp1_hit":      False,
        "sl_order_id":  result["sl_order_id"],
        "tp1_order_id": result["tp1_order_id"],
        "tp2_order_id": result["tp2_order_id"],
        "pump_pct":     signal["pump_pct"],
    }
    add_position(state, position)

    # ── 텔레그램 알림 ─────────────────────────────────────────────────────────
    tg.notify_enter(
        symbol=symbol,
        entry_price=result["entry_price"],
        margin=margin,
        notional=notional,
        sl_price=result["sl_price"],
        tp1_price=result["tp1_price"],
        tp2_price=result["tp2_price"],
        equity=equity,
    )


def run(exchange: ccxt.binanceusdm, dry_run: bool = False) -> None:
    """
    메인 트레이딩 루프

    Parameters
    ----------
    exchange : 인증된 바이낸스 클라이언트
    dry_run  : True = 주문 없이 신호만 로그 출력
    """
    logger.info("=" * 60)
    logger.info("  알트코인 눌림목 롱 전략 시작")
    logger.info(f"  {'[DRY RUN]' if dry_run else '[실거래 모드]'}")
    logger.info("=" * 60)

    tg.notify_start(dry_run)

    # 상태 복원 (봇 재시작 시 이전 포지션 이어받기)
    state = load_state()

    # 급등 감지 대기 큐 (scan_all 이 직접 수정)
    pending_signals = state["pending_signals"]

    last_scan_hour   = -1      # 마지막 심볼 스캔 시(hour)
    last_report_date = None    # 오늘 아침 보고 여부

    while True:
        try:
            now_kst  = datetime.now(KST)
            equity   = get_total_balance(exchange)
            free_bal = get_usdt_balance(exchange)

            # ── 매일 09:00 KST 아침 보고 ─────────────────────────────────────
            if (now_kst.hour == DAILY_REPORT_HOUR
                    and last_report_date != now_kst.date()):
                _send_morning_report(state, equity)
                last_report_date = now_kst.date()

            # ── 오픈 포지션 모니터링 (매 60초) ───────────────────────────────
            if state["open_positions"]:
                check_all_positions(exchange, state)

            # ── 1시간봉 마감마다 심볼 스캔 ───────────────────────────────────
            if _is_candle_hour(last_scan_hour):
                last_scan_hour = datetime.now(timezone.utc).hour
                open_symbols   = get_open_symbols(state)

                logger.info(
                    f"[스캔] 심볼 스캔 시작 | 자본=${equity:,.0f} "
                    f"| 포지션 {len(open_symbols)}개 | 감시 {len(pending_signals)}개"
                )

                signals = scan_all(
                    exchange, SCAN_SYMBOLS, pending_signals, open_symbols
                )

                # 신호별 진입 시도
                for signal in signals:
                    # 스캔 중 다른 진입으로 자본/포지션 수 변경될 수 있어 매번 재조회
                    equity = get_total_balance(exchange)
                    _execute_entry(exchange, state, signal, equity, dry_run)

            save_state(state)

            logger.debug(
                f"[상태] 포지션={len(state['open_positions'])}개 "
                f"감시={len(pending_signals)}개 "
                f"잔고=${free_bal:,.0f}"
            )

            time.sleep(SCAN_INTERVAL_SEC)

        except KeyboardInterrupt:
            logger.info("\n[종료] Ctrl+C - 루프 종료")
            tg.notify_stop()
            break

        except ccxt.NetworkError as e:
            logger.error(f"[네트워크] 오류: {e} - 30초 후 재시도")
            tg.notify_error(f"네트워크 오류: {e}")
            time.sleep(30)

        except ccxt.ExchangeError as e:
            logger.error(f"[거래소] 오류: {e} - 60초 후 재시도")
            tg.notify_error(f"거래소 오류: {e}")
            time.sleep(60)

        except Exception as e:
            logger.exception(f"[예외] {e} - 30초 후 재시도")
            tg.notify_error(f"예외 발생: {e}")
            time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="알트코인 눌림목 롱 전략 - Half Kelly 11% x 5x",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="주문 없이 신호만 출력 (처음 시작 시 필수)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="디버그 로그 출력",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="확인 프롬프트 건너뜀 (systemd 등 비대화형 환경)",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    # 실거래 모드 재확인
    if not args.dry_run and not args.yes:
        print("\n[경고] 실거래 모드입니다. 실제 주문이 실행됩니다.")
        answer = input("계속하려면 'yes' 입력: ")
        if answer.strip().lower() != "yes":
            print("취소됨.")
            sys.exit(0)

    exchange = create_client()
    if not check_connection(exchange):
        logger.error("API 연결 실패 - 종료")
        sys.exit(1)

    run(exchange, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
