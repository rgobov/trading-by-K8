# ISTS — Инвестиционно-Спекулятивная Торговая Система

Основана на динамическом методе оценки конкурентоспособности предприятий Д. С. Воронова.

## Суть стратегии

1. **Отбор**: покупаются только финансово устойчивые компании роста (K > 1.1)
2. **Вход**: покупка по Close за 1 сессию до публикации квартального отчета
3. **Выход**: продажа по Close на следующий торговый день после отчета
4. **Держание**: ~1 день (краткосрочная спекуляция на фундаментальном отборе)

## Формула K (динамический метод Воронова)

```
K = KI × KR × KF
```

- **KI** (стратегическое позиционирование) — насколько быстро компания растет относительно конкурентов
- **KR** (операционная эффективность) — насколько эффективно компания превращает выручку в прибыль
- **KF** (финансовое состояние) — насколько компания ликвидна и финансово устойчива

### Детальный расчет каждого компонента

#### 1. Индекс изменения выручки (IA)

```
IA = S_t / S_{t-1}
```

где:
- `S_t` — выручка компании за текущий квартал (период)
- `S_{t-1}` — выручка компании за аналогичный квартал прошлого года (YoY)

Пример: если выручка AAPL в Q1 2025 = $124.3 млрд, а в Q1 2024 = $119.6 млрд, то `IA = 124.3 / 119.6 = 1.039` (рост 3.9%).

#### 2. Операционная эффективность (RA)

```
RA = S / E = S / (S - NI)
```

где:
- `S` — выручка за период
- `NI` — чистая прибыль за период
- `E = S - NI` — издержки (все расходы, включая себестоимость, налоги, проценты)

Пример: AAPL, S = $124.3 млрд, NI = $36.3 млрд
- E = 124.3 - 36.3 = $88.0 млрд
- RA = 124.3 / 88.0 = 1.413

RA всегда ≥ 0. Если RA = 1.0 — прибыль нулевая. Если RA > 1.0 — компания прибыльна.

#### 3. Уровень ликвидности (FA)

```
FA = ∛(CA / CL)
```

где:
- `CA` — оборотные активы (Current Assets) на конец периода
- `CL` — краткосрочные обязательства (Current Liabilities) на конец периода
- Кубический корень берется для сглаживания дисперсии (коэффициент вариации > 70% для raw current ratio)

Пример: AAPL, CA = $133.2 млрд, CL = $144.4 млрд
- CA / CL = 133.2 / 144.4 = 0.922
- FA = ∛(0.922) = 0.973

#### 4. Коэффициент стратегического позиционирования (KI)

```
KI = IA / IS
```

где:
- `IA` — индекс роста выручки анализируемой компании
- `IS` — индекс роста выручки конкурентов (суммарно)

IS считается как агрегированный индекс роста для группы конкурентов:
```
IS = ΣS_competitors_t / ΣS_competitors_{t-1}
```

Если KI > 1.0 — компания растет быстрее конкурентов.
Если KI < 1.0 — компания отстает от конкурентов.

#### 5. Коэффициент операционной эффективности (KR)

```
KR = RA / RS
```

где:
- `RA` — операционная эффективность компании
- `RS` — операционная эффективность конкурентов

```
RS = ΣS_competitors / ΣE_competitors
```

Если KR > 1.0 — компания эффективнее конкурентов.

#### 6. Коэффициент финансового состояния (KF)

```
KF = FA / FS
```

где:
- `FA` — уровень ликвидности компании
- `FS` — уровень ликвидности конкурентов

```
FS = ∛(ΣCA_competitors / ΣCL_competitors)
```

Если KF > 1.0 — компания ликвиднее конкурентов.

### Итоговый K

```
K = KI × KR × KF
```

### Пример расчета (AAPL, Q1 2025, в сравнении с MSFT)

| Показатель | AAPL | MSFT (конкурент) |
|------------|:----:|:----------------:|
| S_t | $124.3B | $69.6B |
| S_{t-1} | $119.6B | $62.0B |
| NI_t | $36.3B | $24.1B |
| CA_t | $133.2B | $149.3B |
| CL_t | $144.4B | $87.6B |

**Расчет:**
- IA = 124.3 / 119.6 = 1.039
- IS = 69.6 / 62.0 = 1.123
- KI = 1.039 / 1.123 = 0.925

- RA = 124.3 / (124.3 - 36.3) = 124.3 / 88.0 = 1.413
- RS = 69.6 / (69.6 - 24.1) = 69.6 / 45.5 = 1.530
- KR = 1.413 / 1.530 = 0.924

- FA = ∛(133.2 / 144.4) = ∛(0.922) = 0.973
- FS = ∛(149.3 / 87.6) = ∛(1.704) = 1.194
- KF = 0.973 / 1.194 = 0.815

- **K = 0.925 × 0.924 × 0.815 = 0.697** (ниже порога 1.1, не проходит)

**Интерпретация K:**
| K | Уровень |
|---|---------|
| < 0.5 | Крайне низкий |
| 0.5–0.9 | Низкий |
| 0.9–1.0 | Умеренно низкий |
| 1.0–1.1 | Удовлетворительный |
| 1.1–1.3 | Умеренно высокий |
| 1.3–1.7 | Высокий |
| > 1.7 | Крайне высокий |

## Управление капиталом

### Формулы позиционирования

**Базовая доля на позицию:**
```
base_share = MAX_DEPOSIT_PER_POSITION = 0.33 (33% капитала)
```

**K-взвешенный множитель:**
```
k_mult = min(K / 1.1, 3.0)
```

**Итоговая доля:**
```
pos_share = min(base_share × k_mult, 0.5)  # не больше 50%
```

**Размер позиции:**
- Compounding: `position = current_capital × pos_share`
- Fixed: `position = initial_capital × pos_share`

Пример: капитал = $5000, K = 2.0
- k_mult = min(2.0 / 1.1, 3.0) = min(1.82, 3.0) = 1.82
- pos_share = min(0.33 × 1.82, 0.5) = 0.5
- Compounding: position = 5000 × 0.5 = $2500
- Fixed: position = 1500 × 0.5 = $750

### Синхронизация сделок

Для честного сравнения compounding vs fixed сделка выполняется только если:
```
int(initial_capital × pos_share / buy_price) >= 1
```
то есть с начального капитала можно купить хотя бы 1 акцию.

## Комиссии и проскальзывания

| Параметр | Значение |
|----------|----------|
| Комиссия на вход | 0.035% |
| Комиссия на выход | 0.035% |
| Проскальзывание | 0.1% на сделку |

**Итоговая стоимость сделки:**
```
cost = shares × buy_price × (1 + commission_buy + slippage)
proceeds = shares × sell_price × (1 - commission_sell - slippage)
PnL = proceeds - cost
```

## Результаты бэктеста (S&P 500, 5 лет, без Healthcare)

| Вариант | CAGR | maxDD | Win rate | Сделок |
|---------|:----:|:-----:|:--------:|:------:|
| Fixed | 31.5% | 43.4% | 51.2% | 1169 |
| **Compounding** | **81.0%** | **45.2%** | 50.9% | 1104 |

Максимальная серия убытков: **8** подряд. Средняя: 1.9.
Максимум одновременных позиций: **3**. Портфельное ограничение соблюдено.

Volatility-based sector weights: Technology 0.60, Communication Services 0.59, Industrials 1.94, Consumer Defensive 2.0.

## Исключенные сектора

```
Financial Services, Insurance, Banks, Capital Markets,
Consumer Defensive, Utilities, Real Estate, Energy, Healthcare
```

## Структура проекта

```
trading-by-K8/
├── pipeline.py              # Пошаговый запуск пайплайна
├── pipeline_full.py         # Полный автоматический пайплайн
├── overnight_pipeline.py    # Ночной пайплайн (SEC + K + filter + backtest + ML)
├── run_slippage.py          # Бэктест с проскальзываниями
├── requirements.txt
├── src/
│   ├── config.py            # Все настройки (пороги, комиссии, пути)
│   ├── screener.py          # Сбор US тикеров + фильтр по market cap
│   ├── edgar_parser.py      # Парсер SEC EDGAR (Revenue, NI, CA, CL)
│   ├── earnings_calendar.py # Даты отчетов (yfinance + Nasdaq fallback)
│   ├── calculator.py        # Расчет K = KI × KR × KF
│   ├── filter.py            # Отбор по K > порога, секторам
│   ├── backtest.py          # Симуляция сделок
│   └── visualize.py         # Графики
├── data/
│   ├── raw/                 # Сырые данные (SEC, тикеры, кэш)
│   └── processed/           # Результаты (K, фильтр, сделки)
└── output/                  # Графики, логи, ML модель
```

## Пайплайн

### 1. Screener
```
get_all_tickers() → filter by market cap > $500M → exclude ETF/SPAC/REIT
```

### 2. SEC EDGAR Parser
```
Для каждого тикера:
  CIK = ticker_to_cik[ticker]
  facts = GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
  Извлечь: Revenues, NetIncomeLoss, AssetsCurrent, LiabilitiesCurrent
  Дедикация по end_date (один entry per date)
  Сохранить в data/raw/{ticker}_fundamentals.csv
```

### 3. K Calculator
```
Для каждого тикера:
  Загрузить fundamentals
  Сгруппировать по fp (Q1, Q2, Q3, FY)
  Для каждого квартала:
    IA = Revenue_t / Revenue_{t-1, same fp}  # YoY
    RA = Revenue / (Revenue - NetIncome)
    FA = cube_root(CurrentAssets / CurrentLiabilities)
    KI = IA / IA_competitors (1.0 если нет конкурентов)
    KR = RA / RA_competitors
    KF = FA / FA_competitors
    K = KI × KR × KF
```

### 4. Filter
```
K > 1.1 минимум в 2 из 3 последних кварталов
Исключить сектора (Financial Services, Healthcare, etc.)
```

### 5. Backtest
```
Для каждого кандидата:
  earnings_dates = yfinance earnings_dates (только с Reported EPS)
  Для каждой даты отчета:
    buy_date = earnings_date - 1 день
    sell_date = earnings_date + 1 день
    buy_price = Close[buy_date]
    sell_price = Close[sell_date]
    Если нельзя купить 1 акцию — пропустить (синхронизация сделок)
    P&L = sell_price × shares - buy_price × shares - комиссии - slippage
```

### 6. ML (опционально)
```
RandomForestClassifier
Features: K_avg, K_latest, KI_avg, KR_avg, KF_avg
Target: pnl > 0
```

## Источники данных

| Данные | Источник |
|--------|----------|
| Цены | yfinance batch download |
| Фундаментальные (Revenue, NI, CA, CL) | SEC EDGAR XBRL JSON API |
| Даты отчетов | yfinance earnings_dates (только фактические) |
| Сектора | yfinance Ticker.info |
| Список S&P 500 | GitHub dataset |

## Деплой на сервер

### 1. Клонировать и настроить

```bash
ssh user@server
sudo mkdir -p /opt/trading-by-K8
sudo chown $USER:$USER /opt/trading-by-K8
git clone https://github.com/rgobov/trading-by-K8.git /opt/trading-by-K8
cd /opt/trading-by-K8
cp .env.example .env
# заполнить TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID (либо SMTP данные для email)
```

### 2. Копировать накопленные данные

С локальной машины перенести кэш данных (если есть):
```bash
scp data/raw/*.csv user@server:/opt/trading-by-K8/data/raw/
scp data/raw/ticker_sectors.json user@server:/opt/trading-by-K8/data/raw/
```

### 3. Собрать и запустить

```bash
docker compose build
# Первый ручной запуск (загрузка данных)
docker compose run --rm daily-runner
```

### 4. CRON (ежедневно в 22:00 МСК)

```bash
crontab -e
# добавить строку:
0 22 * * * cd /opt/trading-by-K8 && docker compose run --rm daily-runner >> output/cron.log 2>&1
```

### 5. Обновление кода

```bash
cd /opt/trading-by-K8
git pull
docker compose build
```

---

## Команды

```bash
# Полный пайплайн
python3 pipeline.py

# Ночной пайплайн (SEC + K + backtest)
python3 overnight_pipeline.py

# Бэктест с slippage
python3 run_slippage.py

# Проверить статус
tail -20 output/overnight.log
grep "return=" output/slippage.log

# Telegram сигналы
python3 daily_runner.py
```
