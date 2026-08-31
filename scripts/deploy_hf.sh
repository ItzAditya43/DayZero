#!/usr/bin/env bash
# Deploy DayZero to a free Hugging Face Space (Docker SDK).
#
#   ./scripts/deploy_hf.sh <hf-username> [space-name]
#
# Prerequisites, all free and none needing a credit card:
#   1. A Hugging Face account.
#   2. pip install -U "huggingface_hub[cli]" && hf auth login
#      (create a token with WRITE scope at huggingface.co/settings/tokens)
set -euo pipefail

USER="${1:?usage: deploy_hf.sh <hf-username> [space-name]}"
SPACE="${2:-dayzero}"
REPO="https://huggingface.co/spaces/${USER}/${SPACE}"
WORK="$(mktemp -d)"

echo "==> Creating the Space (skipped if it already exists)"
hf repo create "${USER}/${SPACE}" --repo-type space --space_sdk docker -y 2>/dev/null \
  || echo "    already exists, continuing"

echo "==> Cloning ${REPO}"
git clone "${REPO}" "${WORK}/space"

echo "==> Copying the project in"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
rsync -a --delete \
  --exclude '.git' --exclude 'node_modules' --exclude 'dist' \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  "${ROOT}/" "${WORK}/space/"

# The Space needs its own README with the YAML frontmatter that configures it.
cp "${ROOT}/deploy/README_SPACE.md" "${WORK}/space/README.md"

cd "${WORK}/space"
git add -A
git commit -m "Deploy DayZero" || { echo "    nothing changed"; exit 0; }
git push

echo
echo "==> Done. The Space builds in a few minutes at:"
echo "    https://huggingface.co/spaces/${USER}/${SPACE}"
