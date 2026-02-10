FROM python:3.11-slim

WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

EXPOSE 8000

# Railway edge may reach the service over IPv4 and/or IPv6. Start a Uvicorn server
# with pre-bound sockets to reliably accept both, avoiding platform dual-stack quirks.
CMD ["sh", "-c", "python -m src.server"]
