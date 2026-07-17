# Production-oriented image for the FastAPI foundation. Runtime configuration is injected.
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/server:/app

WORKDIR /app

RUN groupadd --system samslab && useradd --system --gid samslab --create-home samslab

COPY pyproject.toml README.md ./
COPY server ./server
COPY shared ./shared
RUN pip install --no-cache-dir .

USER samslab
EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
