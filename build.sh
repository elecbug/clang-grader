#!/usr/bin/env bash
set -euo pipefail

# Image name can be changed as you like
IMAGE_NAME="c-stdin-tester"

# Build using the local 'dockerfile'
docker build -t "${IMAGE_NAME}" -f dockerfile .
echo "Built image: ${IMAGE_NAME}"
