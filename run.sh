#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Usage examples:
#   ./run.sh hw-test
#   ./run.sh data/hw-test
#   GITHUB_TOKEN=ghp_xxx ./run.sh hw-test
# ============================================================

IMAGE_NAME="c-stdin-tester"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="${ROOT_DIR}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <suite-folder or data/suite-folder>"
  exit 1
fi

ARG_SUITE="$1"

# Normalize suite
CLEAN_SUITE="${ARG_SUITE#data/}"
CLEAN_SUITE="${CLEAN_SUITE#./}"
SUITE_NAME="${CLEAN_SUITE}"
SUITE_DIR="${WORK_DIR}/data/${SUITE_NAME}"
TESTS_PATH="${SUITE_DIR}/tests.json"
MAP_JSON="${SUITE_DIR}/student_map.json"

# Checks
[[ -d "${SUITE_DIR}" ]] || { echo "Suite directory not found: ${SUITE_DIR}"; exit 1; }
[[ -f "${TESTS_PATH}" ]] || { echo "tests.json not found: ${TESTS_PATH}"; exit 1; }
[[ -f "${MAP_JSON}"  ]] || { echo "Mapping JSON not found: ${MAP_JSON}"; exit 1; }
sudo docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1 || { echo "Build image first: ./build.sh"; exit 1; }

# 1) Fetch & stage (dir-scope; preserve subdirs; respect limit)
echo "========================================"
echo "Fetching sources using ${MAP_JSON} into ${SUITE_DIR}"
python3 "${WORK_DIR}/fetch_and_stage.py" \
  --map "${MAP_JSON}" \
  --suite "${SUITE_NAME}" \
  --data-root "${WORK_DIR}/data" \
  --rename-to "main.c" \
  --scope "dir" \
  --preserve-subdirs \
  --respect-limit || { echo "Fetch step failed."; exit 1; }

# 2) Grade each student under suite
REPORT_DIR="${WORK_DIR}/reports/${SUITE_NAME}"
mkdir -p "${REPORT_DIR}"

echo "========================================"
echo "Running tests for suite '${SUITE_NAME}'..."
shopt -s nullglob
stu_dirs=("${SUITE_DIR}"/*/)
[[ ${#stu_dirs[@]} -gt 0 ]] || { echo "No student directories found under ${SUITE_DIR}"; exit 1; }

total_students=0
failed_students=0

for d in "${stu_dirs[@]}"; do
  stu_name="$(basename "${d%/}")"
  total_students=$((total_students+1))

  echo "----------------------------------------"
  echo "Student: ${stu_name}"

  BIN_PATH="/work/data/${SUITE_NAME}/${stu_name}/a.out"
  REPORT_PATH="/work/reports/${SUITE_NAME}/${stu_name}.json"

  MAIN_HINT_PATH="${d}/.main_filename"
  MAIN_FILE="main.c"
  if [[ -f "${MAIN_HINT_PATH}" ]]; then
    MAIN_FILE="$(tr -d '\r' < "${MAIN_HINT_PATH}" | sed 's/[[:space:]]*$//')"
  fi

  set +e
  sudo docker run --rm \
    -v "${WORK_DIR}:/work:rw" \
    -e GITHUB_TOKEN \
    --user "$(id -u):$(id -g)" \
    --cpus="1.0" --memory="256m" --pids-limit=256 \
    --network=none --security-opt no-new-privileges --cap-drop ALL \
    --tmpfs /tmp:rw,size=64m \
    "${IMAGE_NAME}" \
      --suite-name "${stu_name}" \
      --src-dir "/work/data/${SUITE_NAME}/${stu_name}" \
      --tests "/work/data/${SUITE_NAME}/tests.json" \
      --bin "${BIN_PATH}" \
      --timeout 2.0 \
      --normalize-newlines \
      --main-filename "${MAIN_FILE}" \
      --report "${REPORT_PATH}"
  rc=$?
  set -e

  if [[ $rc -ne 0 ]]; then
    failed_students=$((failed_students+1))
  fi
done

echo "========================================"
echo "Per-student summary table for suite '${SUITE_NAME}':"
sudo docker run --rm \
  -v "${WORK_DIR}:/work" \
  "${IMAGE_NAME}" \
    --summarize-dir "/work/reports/${SUITE_NAME}"

echo "========================================"
echo "Students graded: ${total_students}, Failures (any test failed or compilation error): ${failed_students}"
echo "Reports saved under: ${REPORT_DIR}"
