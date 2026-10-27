FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY cegar_harness ./cegar_harness
COPY tests ./tests
COPY scripts ./scripts

RUN pip install --no-cache-dir -e ".[dev]" && chmod +x scripts/run_benchmark.sh

CMD ["bash", "scripts/run_benchmark.sh"]
