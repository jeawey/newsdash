FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 1. Install dependencies first (cached unless pyproject.toml changes)
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip && pip install .

# 2. Copy source code (changes frequently, rebuilds only from here)
COPY app ./app
COPY worker ./worker
COPY scripts ./scripts
COPY config ./config

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
