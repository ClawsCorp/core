FROM python:3.11-slim

WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

EXPOSE 8000

# Railway can route to services over IPv4 and/or IPv6.
# Binding both 0.0.0.0 and [::] can fail with EADDRINUSE on hosts where the IPv6
# socket is dual-stack (accepts IPv4). Binding [::] alone is sufficient there.
CMD ["sh", "-c", "hypercorn src.main:app --bind [::]:${PORT:-8000}"]
