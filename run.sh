#!/usr/bin/env bash
set -euo pipefail

# Config
IMAGE_NAME="c-stdin-tester"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="${ROOT_DIR}"
DATA_DIR="${WORK_DIR}/data"
REPORT_DIR="${WORK_DIR}/reports"

# Prepare report directory
mkdir -p "${REPORT_DIR}"

# Sanity checks
if [[ ! -f "${DATA_DIR}/tests.json" ]]; then
  echo "tests.json not found at ${DATA_DIR}/tests.json"
  exit 1
fi

# Grade each student folder (expects main.c)
shopt -s nullglob
stu_dirs=("${DATA_DIR}"/*/)
if [[ ${#stu_dirs[@]} -eq 0 ]]; then
  echo "No student directories under ${DATA_DIR}"
  exit 1
fi

echo "Running tests for each student..."
total_students=0
failed_students=0

for d in "${stu_dirs[@]}"; do
  # Skip non-student directories (e.g., if tests.json is inside a directory)
  if [[ ! -f "${d}/main.c" ]]; then
    continue
  fi

  stu_name="$(basename "${d%/}")"
  total_students=$((total_students+1))

  # Per-student binary path to keep artifacts separate (optional)
  BIN_PATH="/work/data/${stu_name}/a.out"
  REPORT_PATH="/work/reports/${stu_name}.json"

  echo "----------------------------------------"
  echo "Student: ${stu_name}"

  # Run container to compile & test this student
  set +e
  docker run --rm \
    -v "${WORK_DIR}:/work" \
    "${IMAGE_NAME}" \
      --suite-name "${stu_name}" \
      --src "/work/data/${stu_name}/main.c" \
      --tests "/work/data/tests.json" \
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
echo "Per-student summary table:"
# Use the same container to summarize all JSON reports
docker run --rm \
  -v "${WORK_DIR}:/work" \
  "${IMAGE_NAME}" \
    --summarize-dir "/work/reports"

echo "========================================"
echo "Students graded: ${total_students}, Failures (any test failed or compilation error): ${failed_students}"
