# Pinned to bookworm (Debian 12) on purpose. The bare `python:3.12-slim` tag now
# resolves to Debian 13 (trixie), where `playwright install --with-deps` (below)
# fails: Playwright 1.49.1 has no Debian-13 dependency list, so it falls back to
# package names (ttf-unifont, ttf-ubuntu-font-family) that trixie removed, aborting
# the build. Debian 12 is the distro Playwright 1.49.1 targets, so --with-deps
# resolves cleanly here. (To move to trixie later, also bump playwright to a
# version that supports Debian 13.)
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the Chromium browser + its OS libraries that Pro auto-submit drives.
# --with-deps pulls the system packages Chromium needs on Debian slim. If this
# layer is ever removed, auto-submit degrades safely to the manual hand-off
# (application_submit.py returns "unavailable") rather than breaking the app.
RUN python -m playwright install --with-deps chromium

COPY . .

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
