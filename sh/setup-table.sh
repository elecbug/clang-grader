#!/usr/bin/env bash
set -euo pipefail

# perrun.sh
# Usage:
#   ./perrun.sh hw-01 2025-09-09T00:00:00+09:00
#   ./perrun.sh data/hw-01 2025-09-09T00:00:00+09:00
#
# This script normalizes the suite path, locates data/<suite>/table.txt,
# and generates data/<suite>/student_map.json using script/make_student_map.py.

# --- Resolve repo root and script paths
ROOT_DIR="$(pwd)"
SCRIPT_PATH="${ROOT_DIR}/script/make_student_map.py"
PYTHON_BIN="${PYTHON:-python3}"

# --- Args
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <suite-folder or data/suite-folder> <ISO8601-limit>"
  echo "Example: $0 hw-01 2025-09-09T00:00:00+09:00"
  exit 1
fi

ARG_SUITE="$1"
LIMIT_ISO="$2"

# --- Normalize suite name (strip leading 'data/' or './')
CLEAN_SUITE="${ARG_SUITE#data/}"
CLEAN_SUITE="${CLEAN_SUITE#./}"
SUITE_NAME="${CLEAN_SUITE}"

TABLE_TXT_NAME=$(cat $(pwd)/sh/name/STUDENT_TABLE_NAME)
STUDENT_MAP_NAME=$(cat $(pwd)/sh/name/STUDENT_MAP_NAME)

DATA_DIR="${ROOT_DIR}/${SUITE_NAME}"
TABLE_TXT="${DATA_DIR}/${TABLE_TXT_NAME}"
OUT_JSON="${DATA_DIR}/${STUDENT_MAP_NAME}"

# --- Checks
[[ -f "${SCRIPT_PATH}" ]] || { echo "Not found: ${SCRIPT_PATH}"; exit 1; }
[[ -d "${DATA_DIR}"   ]] || { echo "Suite directory not found: ${DATA_DIR}"; exit 1; }
[[ -f "${TABLE_TXT}"  ]] || { echo "Input table not found: ${TABLE_TXT}"; exit 1; }

# --- Make parent dir for output just in case
mkdir -p "${DATA_DIR}"

# --- Run converter
echo "Generating ${STUDENT_MAP_NAME} for suite '${SUITE_NAME}' with limit '${LIMIT_ISO}'..."
"${PYTHON_BIN}" "${SCRIPT_PATH}" \
  "${TABLE_TXT}" \
  --limit "${LIMIT_ISO}" \
  --only-submitted \
  --pretty \
  --include-nonfile \
  -o "${OUT_JSON}"

echo "Done."
echo " -> Output: ${OUT_JSON}"
