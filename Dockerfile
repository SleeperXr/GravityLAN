# HomeLan Docker Image — Multi-Stage Build
# Stage 1: Build React Frontend
FROM node:20-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit
COPY frontend/ ./
RUN npm run build

# Stage 2: Python Build Environment (Builder)
FROM python:3.12-slim AS python-build

# Install compiler tools for compiling raw extensions if wheels are missing
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Create virtual environment to isolate dependencies cleanly
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY backend/requirements.txt ./
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Stage 3: Clean Python Runtime
FROM python:3.12-slim AS runtime

# Install runtime-only system dependencies (absolutely no gcc/python3-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    libcap2-bin \
    iputils-ping \
    avahi-utils \
    iproute2 \
    dnsutils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Grant nmap capabilities so we don't need to run as root
RUN setcap cap_net_raw,cap_net_admin,cap_net_bind_service+eip /usr/bin/nmap

# Copy virtual environment from python-build stage
COPY --from=python-build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy version file, agent script and backend code
COPY VERSION .
COPY agent ./agent
COPY backend/ .

# Copy frontend build to static directory
COPY --from=frontend-build /build/frontend/dist ./static

# Create data directory and user
RUN mkdir -p /app/data && \
    useradd -m -s /bin/bash gravitylan && \
    chown -R gravitylan:gravitylan /app

# Define Volume
VOLUME ["/app/data"]

# Environment
ENV GRAVITYLAN_DATA_DIR=/app/data
ENV GRAVITYLAN_DEBUG=false

# Expose port
EXPOSE 8000

# Run as non-root user
USER gravitylan

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://127.0.0.1:${GRAVITYLAN_PORT:-8000}/api/health || exit 1

# Start server
# Using 1 worker for stability and predictability in homelab environments.
# For larger deployments, increase workers or use a task queue for heavy jobs.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${GRAVITYLAN_PORT:-8000} --workers 1"]
