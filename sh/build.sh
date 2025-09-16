#!/usr/bin/env bash
set -euo pipefail

# Image name can be changed as you like
IMAGE_NAME=$(cat $(pwd)/sh/name/IMAGE_NAME)

# Build using the local 'dockerfile'
sudo docker build -t "${IMAGE_NAME}" docker
echo "Built image: ${IMAGE_NAME}"
