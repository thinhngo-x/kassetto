# ytm: self-hosted YouTube Music client. Stage 1 builds the Svelte frontend (web/), stage 2 is the Python
# backend (app.py + recommend.py) serving it. yt-dlp needs a JS runtime for YouTube -> deno.
FROM node:22.23.5-alpine AS web
WORKDIR /w
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM denoland/deno:bin-2.9.8 AS deno

FROM python:3.12-slim
COPY --from=deno /deno /usr/local/bin/deno
RUN pip install --no-cache-dir "yt-dlp[default]==2026.10.26" ytmusicapi==1.12.4 aiohttp==3.14.5 numpy==2.5.5 \
      PyChromecast==13.1.0 korean-romanizer==0.28.0 pypinyin==0.55.0 pykakasi==2.3.0 anyascii==0.3.3
WORKDIR /app
COPY app.py recommend.py library.py people.py spotify.py phonetics.py castplayer.py /app/
COPY recsys /app/recsys
COPY --from=web /w/dist /app/static
ENV HOME=/tmp PYTHONUNBUFFERED=1
USER 1004:1004
EXPOSE 8090
CMD ["python", "/app/app.py"]
