#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Usage examples:
#   ./run.sh hw-test data/hw-test/student_map.json
#   ./run.sh data/hw-test data/hw-test/student_map.json
#   GITHUB_TOKEN=ghp_xxx ./run.sh hw-test data/hw-test/student_map.json
# ============================================================

IMAGE_NAME="c-stdin-tester"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="${ROOT_DIR}"

# Parse args
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <suite-folder or data/suite-folder>"
  exit 1
fi

ARG_SUITE="$1"

# Normalize suite
CLEAN_SUITE="${ARG_SUITE#data/}"
CLEAN_SUITE="${CLEAN_SUITE#./}"
SUITE_NAME="${CLEAN_SUITE}"                           # e.g., hw-test
SUITE_DIR="${WORK_DIR}/data/${SUITE_NAME}"            # e.g., /repo/data/hw-test
TESTS_PATH="${SUITE_DIR}/tests.json"
MAP_JSON="${SUITE_DIR}/student_map.json"              # e.g., /repo/data/hw-test/student_map.json

# Checks
if [[ ! -f "${MAP_JSON}" ]]; then
  echo "Mapping JSON not found: ${MAP_JSON}"
  exit 1
fi
if [[ ! -d "${SUITE_DIR}" ]]; then
  echo "Suite directory not found: ${SUITE_DIR}"
  exit 1
fi
if [[ ! -f "${TESTS_PATH}" ]]; then
  echo "tests.json not found: ${TESTS_PATH}"
  exit 1
fi
if ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
  echo "Docker image '${IMAGE_NAME}' not found. Build it first:"
  echo "  ./build.sh"
  exit 1
fi

# 1) Fetch & stage sources from GitHub into data/<suite>/<stu>/main.c
echo "========================================"
echo "Fetching sources using ${MAP_JSON} into ${SUITE_DIR}"
python3 "${WORK_DIR}/fetch_and_stage.py" \
  --map "${MAP_JSON}" \
  --suite "${SUITE_NAME}" \
  --data-root "${WORK_DIR}/data" \
  --rename-to "main.c" \
  --keep-original \
  --hash-check \
  --respect-limit || {
    echo "Fetch step failed."
    exit 1
  }

# 2) Grade each student under suite
REPORT_DIR="${WORK_DIR}/reports/${SUITE_NAME}"
mkdir -p "${REPORT_DIR}"

echo "========================================"
echo "Running tests for suite '${SUITE_NAME}'..."
shopt -s nullglob
stu_dirs=("${SUITE_DIR}"/*/)
if [[ ${#stu_dirs[@]} -eq 0 ]]; then
  echo "No student directories found under ${SUITE_DIR}"
  exit 1
fi

total_students=0
failed_students=0

for d in "${stu_dirs[@]}"; do
  if [[ ! -f "${d}/main.c" ]]; then
    continue
  fi
  stu_name="$(basename "${d%/}")"
  total_students=$((total_students+1))

  echo "----------------------------------------"
  echo "Student: ${stu_name}"

  BIN_PATH="/work/data/${SUITE_NAME}/${stu_name}/a.out"
  REPORT_PATH="/work/reports/${SUITE_NAME}/${stu_name}.json"

  set +e
  docker run --rm \
    -v "${WORK_DIR}:/work" \
    "${IMAGE_NAME}" \
      --suite-name "${stu_name}" \
      --src "/work/data/${SUITE_NAME}/${stu_name}/main.c" \
      --tests "/work/data/${SUITE_NAME}/tests.json" \
      --bin "${BIN_PATH}" \
      --timeout 2.0 \
      --normalize-newlines \
      --report "${REPORT_PATH}"
  rc=$?
  set -e

  if [[ $rc -ne 0 ]]; then
    failed_students=$((failed_students+1))
  fi
done

echo "========================================"
echo "Per-student summary table for suite '${SUITE_NAME}':"
docker run --rm \
  -v "${WORK_DIR}:/work" \
  "${IMAGE_NAME}" \
    --summarize-dir "/work/reports/${SUITE_NAME}"

echo "========================================"
echo "Students graded: ${total_students}, Failures (any test failed or compilation error): ${failed_students}"
echo "Reports saved under: ${REPORT_DIR}"
