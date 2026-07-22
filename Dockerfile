FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir --break-system-packages yfinance pandas numpy requests lxml tqdm scikit-learn

COPY src/ ./src/
COPY requirements.txt .
COPY overnight_pipeline.py .
COPY run_slippage.py .
COPY daily_runner.py . 2>/dev/null || true

RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

CMD ["python3", "--version"]
