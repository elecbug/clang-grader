#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Usage:
#   ./run.sh                    # default: data/tests.json in data/ (legacy)
#   ./run.sh hw-test            # uses data/hw-test/tests.json and data/hw-test/stu*/
#   ./run.sh data/hw-test       # same as above
# ============================================================

# Image name built by build.sh
IMAGE_NAME="c-stdin-tester"

# Resolve repo root
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="${ROOT_DIR}"

# ---------- Parse target suite folder ----------
# Accept:
#   - empty (fallback to legacy: data/tests.json + data/*/)
#   - "hw-test"
#   - "data/hw-test"
ARG_SUITE="${1:-}"

# Normalize to a folder name under data/
if [[ -z "${ARG_SUITE}" ]]; then
  # Legacy mode (kept for backward compatibility)
  SUITE_NAME="tests"                              # report folder name
  SUITE_DIR="${WORK_DIR}/data"                    # where stu*/ live
  TESTS_PATH="${WORK_DIR}/data/tests.json"
else
  # If user passed "data/hw-test", strip leading "data/"
  CLEAN_NAME="${ARG_SUITE#data/}"
  # Also strip any leading "./"
  CLEAN_NAME="${CLEAN_NAME#./}"
  SUITE_NAME="${CLEAN_NAME}"                      # e.g., "hw-test"
  SUITE_DIR="${WORK_DIR}/data/${SUITE_NAME}"      # e.g., /repo/data/hw-test
  TESTS_PATH="${SUITE_DIR}/tests.json"
fi

# ---------- Sanity checks ----------
if ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
  echo "Docker image '${IMAGE_NAME}' not found. Build it first:"
  echo "  ./build.sh"
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

# ---------- Reports directory ----------
REPORT_DIR="${WORK_DIR}/reports/${SUITE_NAME}"
mkdir -p "${REPORT_DIR}"

echo "Suite directory : ${SUITE_DIR}"
echo "Tests file      : ${TESTS_PATH}"
echo "Report directory: ${REPORT_DIR}"

# ---------- Collect student directories under suite ----------
shopt -s nullglob
stu_dirs=("${SUITE_DIR}"/*/)
if [[ ${#stu_dirs[@]} -eq 0 ]]; then
  echo "No student directories under ${SUITE_DIR}"
  exit 1
fi

echo "Running tests for each student in '${SUITE_NAME}'..."
total_students=0
failed_students=0

for d in "${stu_dirs[@]}"; do
  # Each student directory must contain main.c
  if [[ ! -f "${d}/main.c" ]]; then
    continue
  fi

  stu_name="$(basename "${d%/}")"
  total_students=$((total_students+1))

  echo "----------------------------------------"
  echo "Student: ${stu_name}"

  # Binary output under the student's own folder for this suite
  # Store inside the same suite path to avoid collisions:
  # e.g., /work/data/hw-test/stu1/a.out
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
