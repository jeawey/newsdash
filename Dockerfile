FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 1. Copy source code and pyproject.toml
COPY pyproject.toml README.md ./
COPY app ./app
COPY worker ./worker
COPY scripts ./scripts
COPY config ./config

# 2. Install dependencies
RUN pip install --upgrade pip && pip install .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]