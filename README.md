# 알트코인 눌림목 롱 전략 봇

알트코인 선물 시장에서 24h 급등(+20%) 이후 고점 -15% 눌림 시 롱 진입하는 자동매매 봇.
7년(2019–2025) 백테스트 최적화 완료. Half Kelly 11% × 레버리지 5x, 바이낸스 Tier 1 한도 적용.

---

## 전략 요약

| 항목 | 내용 |
|------|------|
| 대상 | 바이낸스 알트코인 USDT-M 선물 (39개 심볼) |
| 봉 단위 | 1시간봉 |
| 진입 조건 | 24h +20% 급등 → 고점 -15% 눌림 도달 시 롱 |
| 손절 (SL) | 진입가 -7% (스탑 마켓 주문 — 거래소 등록) |
| 1차 익절 (TP1) | 진입가 +10% (50% 청산) |
| 2차 익절 (TP2) | 진입가 +20% (나머지 50% 청산) |
| 시간손절 | 진입 후 48시간 미청산 시 시장가 청산 |
| 포지션 사이징 | Half Kelly 11% × 5x 레버리지 |
| 마진 모드 | 격리 마진 (심볼별 독립 청산) |
| 일손실 한도 | 일 시작 자본 -10% 초과 시 당일 신규 진입 금지 |

### 7년 백테스트 성과 (2019–2025, 초기 $1,000)

> 바이낸스 Tier 1 노셔널 한도 + 자본 규모별 동시 포지션 한도 현실적 반영

| 지표 | 수치 |
|------|------|
| 최종 자본 | **$388,532** |
| 총 수익률 | **+38,753%** |
| CAGR | **230.9%/년** |
| 최대 낙폭 (MDD) | 52.4% |
| Calmar Ratio | **4.41** |
| 승률 | **57.9%** (655건) |
| Profit Factor | **1.73** |
| 파산 확률 | **0%** (Monte Carlo 10만 회) |

### 연도별 성과

| 연도 | 연수익률 |
|------|---------|
| 2020 | +285% |
| 2021 | +718% |
| 2022 | -13% |
| 2023 | +65% |
| 2024 | +191% |
| 2025 | +104% |

---

## 폴더 구조

```
alt-futures-bot/
├── config/
│   ├── constants.py        # ★ 전략 파라미터 (여기서만 수정)
│   └── settings.py         # .env 환경변수 로드
├── exchange/
│   ├── client.py           # 바이낸스 API (잔고/캔들/주문/포지션)
│   └── order.py            # 진입 플로우 (시장가 + SL/TP 일괄 등록)
├── strategy/
│   ├── scanner.py          # 급등 감지 → 눌림 대기 → 신호 발생
│   └── sizer.py            # Half Kelly 포지션 사이징 + Tier1 체크
├── core/
│   ├── risk.py             # 일손실 + 동시 포지션 한도 체크
│   ├── tracker.py          # SL/TP 체결 감지, 48h 시간손절 처리
│   └── state.py            # JSON 영속 상태 (봇 재시작 시 복원)
├── notifications/
│   └── telegram.py         # 진입/익절/손절/아침보고 텔레그램 알림
├── scripts/
│   ├── check_signals.py    # 현재 급등/눌림 신호 조회 (실거래 없음)
│   ├── check_positions.py  # 오픈 포지션 및 봇 상태 확인
│   └── alt-futures-bot.service  # systemd 서비스 파일 (서버 배포용)
├── data/
│   └── state.json          # 봇 런타임 상태 (자동 생성)
├── logs/                   # 로그 파일 (자동 생성)
├── run_live.py             # ★ 실거래 실행 진입점
├── .env.example            # 환경변수 템플릿
└── requirements.txt
```

---

## 빠른 시작

### 1. 설치

```bash
git clone https://github.com/Power-xc/alt-futures-bot.git
cd alt-futures-bot
pip install -r requirements.txt
```

### 2. 환경 설정

```bash
cp .env.example .env
nano .env
```

```env
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
TELEGRAM_TOKEN=your_token      # 선택
TELEGRAM_CHAT_ID=your_chat_id  # 선택
```

### 3. 드라이런 (신호만 확인 — 처음 시작 시 필수)

```bash
python run_live.py --dry-run
```

### 4. 실거래 시작

```bash
python run_live.py
```

### 5. 상태 확인 스크립트

```bash
# 현재 급등/눌림 신호 조회
python scripts/check_signals.py

# 오픈 포지션 및 봇 상태 확인
python scripts/check_positions.py
```

---

## 서버 배포 (Oracle Cloud Free Tier)

```bash
# 서버에서
git clone https://github.com/Power-xc/alt-futures-bot.git
cd alt-futures-bot
pip install -r requirements.txt
cp .env.example .env && nano .env

# systemd 서비스 등록 (24시간 자동 실행)
sudo cp scripts/alt-futures-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable alt-futures-bot
sudo systemctl start alt-futures-bot

# 로그 확인
sudo journalctl -u alt-futures-bot -f
```

---

## 파라미터 설명 (`config/constants.py`)

### 신호 감지

```python
PUMP_THRESHOLD      = 0.20   # 24h 급등 기준: +20% 이상
PULLBACK_THRESHOLD  = 0.15   # 고점 대비 눌림: -15% 이하
SIGNAL_EXPIRY_HOURS = 48     # 급등 감지 후 신호 유효 시간
```

**핵심 근거**: 즉각 추격 매수 시 승률 42~47%, 눌림 -15% 대기 시 **65~70%** 로 개선

### 포지션 사이징

```python
HALF_KELLY = 0.11   # 증거금 = 자본 × 11%
LEVERAGE   = 5      # 레버리지 5x
```

**Kelly 계산** (7년 백테스트 기반):
```
win_rate = 57.9%,  avg_win/avg_loss = 2.12
Full Kelly = 22.1%  →  Half Kelly = 11% (실전 적용)

예시 (자본 $10,000):
  증거금  = $1,100  (자본 × 11%)
  노셔널  = $5,500  (증거금 × 5x)
  최대 손실 (SL -7%) = $5,500 × 0.07 = $385 = 자본의 3.85%
```

**레버리지 선택 근거** (Calmar 기준):

| 레버리지 | CAGR | MDD | Calmar |
|---------|------|-----|--------|
| 3x | 98.5% | -23.2% | 4.25 |
| **5x** | **230.9%** | **-52.4%** | **4.41 ★** |
| 7x | 312.1% | -74.8% | 4.17 |

### 청산 조건

```python
SL_PCT          = 0.07   # 손절: 진입가 -7%
TP1_PCT         = 0.10   # 1차 익절: +10% (50% 청산)
TP2_PCT         = 0.20   # 2차 익절: +20% (나머지 50%)
TIME_STOP_HOURS = 48     # 시간손절: 48시간
```

### 리스크 관리

```python
DAILY_LOSS_LIMIT = 0.10  # 일손실 한도: 시작 자본 -10%

# 자본 규모별 최대 동시 포지션 수
< $5,000   → 최대 3개
< $20,000  → 최대 5개
< $100,000 → 최대 8개
< $500,000 → 최대 12개
$500,000+  → 최대 20개
```

### 바이낸스 Tier 1 노셔널 한도

심볼별 포지션 한도 초과 시 해당 신호 스킵 (레버리지 낮추지 않음)

| 심볼 | 한도 | 스킵 시작 자본 |
|------|------|-------------|
| BTCUSDT | $5,000,000 | ~$9천만 |
| ETHUSDT | $3,000,000 | ~$5천4백만 |
| SOLUSDT, XRPUSDT | $500,000 | ~$909만 |
| DOTUSDT, LINKUSDT | $200,000 | ~$363만 |
| 소형 알트 | $25,000~75,000 | ~$45만~ |

---

## 전략 로직 상세

### 신호 감지 플로우

```
[매 1시간봉 마감마다 전체 심볼 스캔]

Step 1 — 급등 감지
  24h 종가 변화율 >= +20%
    → 24h 최고가(pump_high) 기록
    → 감시 시작 (최대 48h)

Step 2 — 눌림 대기
  현재가 <= pump_high × (1 - 0.15)
    → 진입 신호 발생!

Step 3 — 리스크 필터 (전부 통과해야 진입)
  ① 일손실 한도 미초과?
  ② 동시 포지션 한도 여유?
  ③ Tier 1 노셔널 한도 미초과?
```

### 주문 실행 플로우

```
[진입 신호 발생 시]

1. setup_symbol()     격리마진 + 5x 레버리지 설정
2. 시장가 롱 진입      notional = equity × 11% × 5
3. SL 스탑마켓 등록    진입가 × 0.93  (거래소에 영구 등록)
4. TP1 지정가 등록     진입가 × 1.10  (50% 수량, GTC)
5. TP2 지정가 등록     진입가 × 1.20  (50% 수량, GTC)
6. 상태 저장           data/state.json

→ SL/TP는 거래소에 등록되어 봇 다운 시에도 자동 체결
```

### 포지션 모니터링 (매 60초)

```
오픈 포지션 있으면 매 사이클 체크:

① 48h 만료 체크
   → 만료 시: 모든 주문 취소 + 시장가 청산

② 거래소 실제 포지션 조회
   → 포지션 소멸: SL 또는 TP2 체결 → 상태 제거 + 텔레그램 알림
   → 수량 50% 감소: TP1 체결 → tp1_hit=True 업데이트 + 텔레그램 알림
```

---

## 봇 운용 주의사항

- 백테스트 과거 데이터 기반 — 미래 수익 보장 없음
- MDD 52.4% — 자본의 절반까지 줄어드는 구간 반드시 대비
- **권장 최소 자본: $500 이상** (마진 최소 단위 고려)
- API Key 발급 시 **출금 권한 절대 체크 금지**
- 바이낸스 서브계정 사용 권장 (기존 봇과 자본 분리)
- 선물 지갑 잔고 확인 후 실행 (현물 지갑 ≠ 선물 지갑)
