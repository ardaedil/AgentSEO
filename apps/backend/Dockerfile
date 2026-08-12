FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /repo
COPY apps/backend/pyproject.toml apps/backend/pyproject.toml
COPY apps/backend/src apps/backend/src
COPY apps/backend/alembic.ini apps/backend/alembic.ini
COPY apps/backend/alembic apps/backend/alembic
RUN pip install --no-cache-dir ./apps/backend
WORKDIR /repo/apps/backend
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn agentseo.main:app --host 0.0.0.0 --port 8000"]

