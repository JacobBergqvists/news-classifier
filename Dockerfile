# Stage 1: Build Next.js static export
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ .
RUN npm run build

# Stage 2: Python backend serving everything
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy Next.js static export into frontend_build/
COPY --from=frontend-builder /app/frontend/out ./frontend_build

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
