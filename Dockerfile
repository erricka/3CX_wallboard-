# One image: React wallboard (static files) served by the FastAPI backend.
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 STATIC_DIR=/app/static
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY --from=frontend /frontend/dist ./static

EXPOSE 8000
# Hosting platforms (Render, Railway, ...) pass the port in $PORT.
CMD uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}
