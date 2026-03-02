FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# 1. Copy pyproject.toml first (cached unless changes)
COPY pyproject.toml README.md ./

# 2. Copy source code
COPY app ./app
COPY worker ./worker
COPY scripts ./scripts
COPY config ./config

# 3. Install dependencies (only runs if pyproject.toml changes)
RUN pip install --upgrade pip && pip install .

# 4. Copy static files last (forces rebuild when they change)
COPY app/static ./app/static

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]