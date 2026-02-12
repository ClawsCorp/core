FROM python:3.11-slim

WORKDIR /app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/contracts

COPY contracts/package.json contracts/package-lock.json /app/contracts/
RUN npm ci --prefix /app/contracts --omit=dev \
    && npm install --prefix /app/contracts --no-save ethers@6

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

EXPOSE 8000

CMD ["sh", "-c", "alembic -c alembic.ini upgrade head && exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
