# STAGE 1: Build
FROM python:3.13-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# COPY poetry.lock .  <-- Uncomment if you have this file

RUN pip install --upgrade pip && \
    pip install --prefix=/install .

# STAGE 2: Runtime
FROM python:3.13-slim-bookworm AS runtime

RUN groupadd -r agent && useradd -r -g agent -s /sbin/nologin agent

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 ca-certificates \
    fonts-liberation libappindicator3-1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

# Install Firefox for Camoufox compatibility
RUN playwright install firefox

RUN chown -R agent:agent /app
USER agent

CMD ["python", "main.py"]