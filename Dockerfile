FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /build/webapp
COPY webapp/package*.json ./
RUN npm ci
COPY webapp/ ./
RUN npm run build


FROM node:20-bookworm-slim AS backend-deps

WORKDIR /build/backend
COPY webapp/backend/package*.json ./
RUN npm ci --omit=dev


FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    PORT=8000 \
    FA_PY=/usr/bin/python3

WORKDIR /app

COPY requirments.txt ./requirments.txt
RUN pip install --no-cache-dir -r requirments.txt

COPY . .
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=backend-deps /build/backend/node_modules ./webapp/backend/node_modules
COPY --from=frontend-builder /build/webapp/dist ./webapp/dist
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh ./webapp/backend/fa_bridge.sh

EXPOSE 8000

CMD ["/entrypoint.sh"]
