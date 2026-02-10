FROM python:3.11-slim

WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

EXPOSE 8000

# Railway can route to services over IPv4 and/or IPv6.
# Uvicorn does not reliably do dual-stack when bound to ::, so use Hypercorn and bind both.
CMD ["sh", "-c", "hypercorn src.main:app --bind 0.0.0.0:${PORT:-8000} --bind [::]:${PORT:-8000}"]
