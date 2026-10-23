# ==============================================================================
# Multi-Stage Dockerfile for Rig Digital Twin Core
# ==============================================================================

# --- Stage 1: Build & Dependencies ---
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip build wheel && \
    pip install --no-cache-dir .

# --- Stage 2: Minimal Secure Runtime ---
FROM python:3.12-slim AS runner

LABEL org.opencontainers.image.title="Rig Digital Twin Core" \
      org.opencontainers.image.description="Real-time drilling simulation and predictive wellbore physics engine" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.authors="kirk-keel" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/home/riguser/.local/bin:$PATH" \
    PYTHONPATH="/app/src:$PYTHONPATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 10001 riguser && \
    useradd -u 10001 -g riguser -m -s /bin/bash riguser

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/rig-twin /usr/local/bin/rig-twin

# Copy application source and configurations
COPY src/ ./src/
COPY configs/ ./configs/
COPY sql/ ./sql/
COPY docker/entrypoint.sh ./docker/entrypoint.sh

RUN chmod +x ./docker/entrypoint.sh && \
    chown -R riguser:riguser /app

USER riguser

EXPOSE 8000 9090

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["rig-twin", "serve", "--host", "0.0.0.0", "--port", "8000"]
