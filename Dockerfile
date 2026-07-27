FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir --break-system-packages \
    yfinance pandas numpy requests lxml tqdm

COPY src/ ./src/
COPY daily_runner.py .
COPY data/raw/sp500_tickers.csv data/raw/

RUN mkdir -p data/raw data/processed output

CMD ["python3", "daily_runner.py"]
