# HomeLan Docker Image — Multi-Stage Build
# Stage 1: Build React Frontend
FROM node:20-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit
COPY frontend/ ./
RUN npm run build

# Stage 2: Python Runtime with FastAPI
FROM python:3.12-slim AS runtime

# Install system dependencies for network scanning
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    net-tools \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir . 2>/dev/null || pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.32.0" \
    "sqlalchemy[asyncio]>=2.0.36" \
    "aiosqlite>=0.20.0" \
    "pydantic>=2.10.0" \
    "pydantic-settings>=2.6.0" \
    "websockets>=13.0" \
    "paramiko>=3.5.0" \
    "dnspython>=2.6.0"

# Copy agent script and backend code
COPY agent ./agent
COPY backend/app ./app

# Copy frontend build
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

# Create data directory
RUN mkdir -p /app/backend/data

# Environment
ENV HOMELAN_DATA_DIR=/app/backend/data
ENV HOMELAN_DEBUG=false

# Expose port (Default 8000 for NPM proxy)
EXPOSE 8000

# Run as root (Required for raw socket nmap scans and Unraid volume permissions)
USER root

# Start server on Port 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
