"""
텔레그램 알림 모듈

설정 방법:
  1. @BotFather -> /newbot -> 토큰 발급
  2. 봇에게 메시지 한 번 전송
  3. https://api.telegram.org/bot<TOKEN>/getUpdates 에서 chat_id 확인
  4. .env 파일에 TELEGRAM_TOKEN, TELEGRAM_CHAT_ID 입력

미설정 시 조용히 스킵 (봇 동작에 영향 없음)
"""
import logging
from datetime import datetime, timezone, timedelta

import requests

from config.settings import get_telegram_credentials

logger = logging.getLogger(__name__)

KST = timedelta(hours=9)

_CREDS  = None   # 초기화 지연 (import 시 .env 미로드 방지)
_OFFSET = 0      # getUpdates long-polling offset


def _get_creds() -> dict:
    global _CREDS
    if _CREDS is None:
        _CREDS = get_telegram_credentials()
    return _CREDS


def _send(text: str) -> bool:
    """텔레그램 메시지 전송. 실패 시 로그만 남기고 False 반환."""
    creds = _get_creds()
    if not creds["token"] or not creds["chat_id"]:
        return False  # 설정 안 됨 -> 조용히 스킵

    url = f"https://api.telegram.org/bot{creds['token']}/sendMessage"
    chat_ids = [creds["chat_id"]]
    extra = creds.get("chat_id_2")
    if extra and extra != creds["chat_id"]:
        chat_ids.append(extra)

    success = False
    for chat_id in chat_ids:
        try:
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
            resp.raise_for_status()
            success = True
        except Exception as e:
            logger.warning(f"[텔레그램] 전송 실패 (무시): {e}")
    return success


def _now_kst() -> str:
    """현재 KST 시각 문자열"""
    return (datetime.now(timezone.utc) + KST).strftime("%m/%d %H:%M")


# ── 공개 API ─────────────────────────────────────────────────────────────────

def notify_start(dry_run: bool = False) -> None:
    """봇 시작 알림"""
    mode = " [DRY RUN]" if dry_run else ""
    _send(
        f"🤖 <b>알트코인 눌림목봇 시작</b>{mode}\n"
        f"Half Kelly 11% x 5x | Tier1 한도 적용\n"
        f"{_now_kst()} KST"
    )


def notify_stop() -> None:
    """봇 종료 알림"""
    _send(f"🔌 알트코인 눌림목봇 종료 ({_now_kst()} KST)")


def notify_enter(symbol: str,
                 entry_price: float,
                 margin: float,
                 notional: float,
                 sl_price: float,
                 tp1_price: float,
                 tp2_price: float,
                 equity: float) -> None:
    """롱 진입 알림"""
    _send(
        f"🟢 <b>{symbol} 롱 진입</b>  {_now_kst()}\n"
        f"진입가: <b>${entry_price:,.4f}</b>\n"
        f"증거금: ${margin:,.0f}  |  노셔널: ${notional:,.0f}\n"
        f"SL: ${sl_price:,.4f}  |  TP1: ${tp1_price:,.4f}  |  TP2: ${tp2_price:,.4f}\n"
        f"잔고: ${equity:,.0f}"
    )


def notify_tp1(symbol: str,
               entry_price: float,
               tp1_price: float,
               pnl: float) -> None:
    """TP1 체결 알림 (50% 익절)"""
    pct = (tp1_price / entry_price - 1) * 100
    _send(
        f"🔁 <b>{symbol} TP1 체결</b>  {_now_kst()}\n"
        f"진입가 ${entry_price:,.4f} -> ${tp1_price:,.4f} ({pct:+.1f}%)\n"
        f"PnL: <b>+${pnl:,.2f}</b>  (50% 익절, 나머지 TP2 대기)"
    )


def notify_close(symbol: str,
                 entry_price: float,
                 exit_price: float,
                 pnl: float,
                 reason: str = "") -> None:
    """포지션 완전 종료 알림 (SL / TP2 / 시간손절)"""
    is_profit = pnl >= 0
    emoji     = "✅" if is_profit else "🛑"
    pnl_str   = f"+${pnl:,.2f}" if is_profit else f"-${abs(pnl):,.2f}"
    pct       = (exit_price / entry_price - 1) * 100

    _send(
        f"{emoji} <b>{symbol} 종료</b>  [{reason}]  {_now_kst()}\n"
        f"${entry_price:,.4f} -> ${exit_price:,.4f} ({pct:+.1f}%)\n"
        f"PnL: <b>{pnl_str}</b>"
    )


def notify_skip(symbol: str, reason: str) -> None:
    """신호 스킵 알림 (정보성, 선택적)"""
    _send(f"⏭ <b>{symbol}</b> 신호 스킵: {reason}")


def notify_error(error: str) -> None:
    """오류 알림"""
    _send(f"⚠️ <b>오류 발생</b>\n{error[:300]}")


def check_commands(state: dict, equity: float) -> None:
    """
    텔레그램 명령어 폴링 및 응답
      /status  - 현재 포지션 + 감시 중 심볼
      /pnl     - 오늘 PnL + 누적 거래 횟수
    """
    global _OFFSET
    creds = _get_creds()
    if not creds["token"] or not creds["chat_id"]:
        return

    try:
        url  = f"https://api.telegram.org/bot{creds['token']}/getUpdates"
        resp = requests.get(url, params={"offset": _OFFSET, "timeout": 1}, timeout=5)
        resp.raise_for_status()
        updates = resp.json().get("result", [])
    except Exception:
        return

    for upd in updates:
        _OFFSET = upd["update_id"] + 1
        msg = upd.get("message", {})
        text = msg.get("text", "").strip().lower()

        if text == "/status":
            positions = state.get("open_positions", [])
            pending   = state.get("pending_signals", {})
            pos_lines = ""
            for p in positions:
                tp1 = "TP1완료" if p["tp1_hit"] else "대기중"
                pos_lines += f"\n  • {p['symbol']} @ ${p['entry_price']:,.4f} [{tp1}]"
            _send(
                f"📊 <b>현황</b>  {_now_kst()} KST\n"
                f"잔고: <b>${equity:,.0f}</b>\n"
                f"오픈 포지션: {len(positions)}개{pos_lines}\n"
                f"감시 중: {len(pending)}개 심볼"
            )

        elif text == "/pnl":
            ds    = state.get("daily_state", {})
            pnl   = ds.get("realized_pnl", 0)
            count = ds.get("trade_count", 0)
            pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
            _send(
                f"💰 <b>오늘 PnL</b>  {_now_kst()} KST\n"
                f"실현 PnL: <b>{pnl_str}</b>  ({count}회 거래)\n"
                f"잔고: ${equity:,.0f}"
            )


def notify_morning_report(equity: float,
                          open_positions: list,
                          daily_pnl: float,
                          trade_count: int,
                          watching: int) -> None:
    """매일 오전 9시 KST 현황 보고"""
    pnl_str = f"+${daily_pnl:,.2f}" if daily_pnl >= 0 else f"-${abs(daily_pnl):,.2f}"

    pos_lines = ""
    for p in open_positions:
        sym         = p["symbol"]
        entry       = p["entry_price"]
        tp1_status  = "TP1완료" if p["tp1_hit"] else "대기중"
        pos_lines  += f"\n  • {sym} @ ${entry:,.4f} [{tp1_status}]"

    _send(
        f"☀️ <b>아침 보고 [알트봇]</b>  {_now_kst()} KST\n"
        f"잔고: <b>${equity:,.0f}</b>  |  오늘 PnL: {pnl_str} ({trade_count}회)\n"
        f"오픈 포지션: {len(open_positions)}개{pos_lines}\n"
        f"감시 중: {watching}개 심볼"
    )
