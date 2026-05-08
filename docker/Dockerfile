# HomeLan Docker Image — Multi-Stage Build
# Stage 1: Build React Frontend
# Stage 2: Python Runtime with FastAPI

# === Stage 1: Frontend Build ===
FROM node:20-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit
COPY frontend/ ./
RUN npm run build

# === Stage 2: Backend Runtime ===
FROM python:3.12-slim AS runtime

# Install system dependencies for network scanning
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    net-tools \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (scanning capabilities added via Docker)
RUN useradd -m -s /bin/bash homelan

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
    "paramiko>=3.5.0"

# Copy agent script and backend code
COPY agent ./agent
COPY backend/app ./app

# Copy frontend build
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

# Create data directory
RUN mkdir -p /data && chown homelan:homelan /data

# Environment
ENV HOMELAN_DATA_DIR=/data
ENV HOMELAN_DEBUG=false

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:80/api/health')" || exit 1

# Run as non-root (with NET capabilities from Docker)
USER homelan

# Start server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80", "--workers", "1"]
