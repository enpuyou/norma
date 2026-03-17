FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app/backend

RUN pip install --no-cache-dir poetry

COPY backend/pyproject.toml backend/poetry.lock* ./
RUN poetry install --no-interaction --no-ansi --without dev

COPY backend/ ./

EXPOSE 8080
CMD ["poetry", "run", "uvicorn", "norma.main:app", "--host", "0.0.0.0", "--port", "8080"]
