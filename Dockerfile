FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install .
COPY ui ./ui
COPY playbooks ./playbooks

EXPOSE 8000 8501
CMD ["uvicorn", "--factory", "auditor.api.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
