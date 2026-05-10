# HomeLan Docker Image — Multi-Stage Build
# Stage 1: Build React Frontend
FROM node:20-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit
COPY frontend/ ./
RUN npm run build

# Stage 2: Python Runtime with FastAPI
FROM python:3.11-slim AS runtime

# Install system dependencies for network scanning
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    iputils-ping \
    avahi-utils \
    iproute2 \
    dnsutils \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent script and backend code
COPY agent ./agent
COPY backend/ .

# Copy frontend build to static directory
COPY --from=frontend-build /build/frontend/dist ./static

# Create data directory
RUN mkdir -p /app/data

# Environment
ENV GRAVITYLAN_DATA_DIR=/app/data
ENV GRAVITYLAN_DEBUG=true

# Expose port
EXPOSE 8000

# Run as root (Required for raw socket nmap scans)
USER root

# Start server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
