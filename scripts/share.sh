#!/usr/bin/env bash
# Put DayZero on a public URL in about 60 seconds, with no account anywhere.
#
#   ./scripts/share.sh
#
# Starts the app locally and opens a Cloudflare quick tunnel to it. You get a
# https://<random>.trycloudflare.com link that anyone can open.
#
# The link lives only while this script runs, so it is for showing someone the
# app right now -- recording the demo video, a mentor session, a teammate on
# another machine. For the submission link, deploy properly (see README).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8000}"
BIN="${ROOT}/.cache/cloudflared"

if ! command -v cloudflared >/dev/null 2>&1 && [ ! -x "${BIN}" ]; then
  echo "==> Fetching cloudflared (one-off, ~35 MB, no account needed)"
  mkdir -p "$(dirname "${BIN}")"
  case "$(uname -m)" in
    x86_64)  ARCH=amd64 ;;
    aarch64) ARCH=arm64 ;;
    *) echo "unsupported architecture: $(uname -m)"; exit 1 ;;
  esac
  curl -fsSL -o "${BIN}" \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}"
  chmod +x "${BIN}"
fi
CF="$(command -v cloudflared || echo "${BIN}")"

if [ ! -d "${ROOT}/frontend/dist" ]; then
  echo "==> Building the frontend first"
  (cd "${ROOT}/frontend" && npm install && npm run build)
fi

echo "==> Starting DayZero on :${PORT}"
(cd "${ROOT}" && uv run uvicorn dayzero.api:app --host 127.0.0.1 --port "${PORT}") &
APP=$!
trap 'kill ${APP} 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null && break
  sleep 1
done

echo "==> Opening the tunnel. Your public link appears below."
"${CF}" tunnel --url "http://127.0.0.1:${PORT}"
