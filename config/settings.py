"""
환경변수 로드 — .env 파일 기반

설정 방법:
  1. .env.example 을 .env 로 복사
  2. 바이낸스 서브계정 API Key / Secret 입력
  3. 텔레그램 Bot Token / Chat ID 입력
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트의 .env 로드
load_dotenv(Path(__file__).parent.parent / ".env")


def get_api_credentials() -> dict:
    """바이낸스 API 인증 정보 반환"""
    key    = os.getenv("BINANCE_API_KEY", "")
    secret = os.getenv("BINANCE_API_SECRET", "")
    if not key or not secret:
        raise EnvironmentError(
            ".env 파일에 BINANCE_API_KEY, BINANCE_API_SECRET 를 설정하세요."
        )
    return {"api_key": key, "api_secret": secret}


def get_telegram_credentials() -> dict:
    """텔레그램 봇 인증 정보 반환 (미설정 시 빈 문자열)"""
    return {
        "token":     os.getenv("TELEGRAM_TOKEN", ""),
        "chat_id":   os.getenv("TELEGRAM_CHAT_ID", ""),
        "chat_id_2": os.getenv("TELEGRAM_CHAT_ID_2", ""),
    }


def is_dry_run() -> bool:
    """DRY_RUN=true 환경변수 확인"""
    return os.getenv("DRY_RUN", "false").lower() == "true"
