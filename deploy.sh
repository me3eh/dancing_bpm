#!/bin/bash
set -e

# ── config (mirrors your deploy.yml) ──────────────────────────────────────
IMAGE="me3eh/dancing-bpm"
SERVER="ubuntu@1.1.1.1"
REGISTRY="localhost:5555"   # your local registry
FULL_IMAGE="$REGISTRY/$IMAGE"

# ── 1. build ───────────────────────────────────────────────────────────────
echo "→ Building image for amd64..."
docker buildx build --platform linux/amd64 -t "$FULL_IMAGE" --push .

# ── 2. deploy ──────────────────────────────────────────────────────────────
echo "→ Deploying to $SERVER..."
ssh "$SERVER" bash << EOF
  docker pull $FULL_IMAGE
  docker stop dancing-bpm 2>/dev/null || true
  docker rm   dancing-bpm 2>/dev/null || true
  docker run -d \
    --name dancing-bpm \
    --restart unless-stopped \
    -p 5000:5000 \
    $FULL_IMAGE
  echo "✓ Container started"
  docker ps --filter name=dancing-bpm
EOF

echo "✓ Done — app running at http://111.11.11.1:5000"
