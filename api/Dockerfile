# syntax=docker/dockerfile:1

FROM node:22-alpine AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
# --legacy-peer-deps: some eslint plugins declare an older peer range, which npm ci refuses.
RUN npm ci --no-audit --no-fund --legacy-peer-deps
COPY web/ ./
# The second pass is the TV build for webOS 4.5, in its own directory so the first
# pass's emptying of dist/ leaves it alone.
RUN npm run build && npm run build:legacy

# Python 3.12 for the type syntax used throughout.
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    VIBESTREAM_WEB_DIR=/app/web

WORKDIR /app

# ffmpeg copies the video stream and encodes audio; VAAPI is for the transcode fallback.
# Intel's media driver exists only for x86_64.
ARG TARGETARCH
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      libva2 \
      libva-drm2 \
      vainfo \
      fonts-noto-core \
      $([ "${TARGETARCH:-amd64}" = amd64 ] && echo intel-media-va-driver) \
 && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY api/vibestream ./vibestream
COPY --from=web /build/dist ./web
COPY --from=web /build/dist-legacy ./web/legacy

# The database and the .torrent cache live on a volume.
RUN mkdir -p /app/data/torrents

# Non-root, with a uid matching the host owner of /data, so its hardlinks stay readable.
ARG PUID=1000
ARG PGID=1000
RUN groupadd -g ${PGID} vibestream 2>/dev/null || true \
 && useradd -u ${PUID} -g ${PGID} -m -s /bin/bash vibestream 2>/dev/null || true \
 && chown -R ${PUID}:${PGID} /app/data
USER ${PUID}:${PGID}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).status==200 else 1)"

# X-Forwarded-For is trusted only from these addresses, or a client could spoof its own
# past the admin sign-in throttle. Set to the reverse proxy's address or subnet.
ENV FORWARDED_ALLOW_IPS=127.0.0.1

# Empty for a release; a commit's short hash for a build from main.
ARG VIBESTREAM_BUILD=""
ENV VIBESTREAM_BUILD=${VIBESTREAM_BUILD}

CMD ["uvicorn", "vibestream.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers"]
