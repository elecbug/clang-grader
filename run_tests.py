#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import subprocess
import sys
import textwrap
from typing import List, Union, Optional

def compile_c(src: str, bin_out: str, cflags: str) -> Optional[str]:
    """Compile the given C source into an executable.
    Returns None on success, or the compiler stderr text on failure.
    """
    cmd = ["gcc"] + shlex.split(cflags) + ["-o", bin_out, src]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return (proc.stdout or "") + (proc.stderr or "")
    return None

def read_tests(tests_path: str) -> List[dict]:
    """Load tests from a JSON file."""
    with open(tests_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("tests.json must be a JSON array of test cases.")
    for i, t in enumerate(data):
        if "name" not in t:
            t["name"] = f"case-{i+1}"
        if "stdin" not in t:
            raise SystemExit(f"Test '{t['name']}' missing 'stdin'.")
        if "expected" not in t:
            raise SystemExit(f"Test '{t['name']}' missing 'expected'.")
    return data

def normalize(s: str, strip_mode: str, normalize_newlines: bool) -> str:
    """Normalize output for comparison."""
    if normalize_newlines:
        s = s.replace("\r\n", "\n").replace("\r", "\n")
    if strip_mode == "left":
        s = s.lstrip()
    elif strip_mode == "right":
        s = s.rstrip()
    elif strip_mode == "both":
        s = s.strip()
    elif strip_mode == "none":
        pass
    else:
        raise ValueError(f"Unknown strip mode: {strip_mode}")
    return s

def run_one(bin_path: str, stdin_data: str, timeout: float) -> subprocess.CompletedProcess:
    """Execute binary with given stdin and timeout, capturing stdout/stderr."""
    return subprocess.run(
        [bin_path],
        input=stdin_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout
    )

def diff_block(expected: str, got: str) -> str:
    """Prepare a compact diff-like block for human readability."""
    exp_vis = expected.replace("\n", "\\n\n")
    got_vis = got.replace("\n", "\\n\n")
    return textwrap.dedent(f"""
    --- expected ---
    {exp_vis}
    ---   got    ---
    {got_vis}
    """).rstrip()

def write_report(report_path: str, payload: dict) -> None:
    """Write JSON report to a path (ensuring parent directory exists)."""
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

def load_report(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def summarize_dir(dir_path: str) -> int:
    """Read all *.json reports and print a human-friendly summary table.
    Returns 0 on success.
    """
    if not os.path.isdir(dir_path):
        print(f"Report directory not found: {dir_path}")
        return 1
    entries = sorted([p for p in os.listdir(dir_path) if p.endswith(".json")])
    if not entries:
        print(f"No reports found in {dir_path}")
        return 1

    # Prepare a table-like output
    print(f"{'Student':<20} {'Pass':>4} {'Total':>5} {'Result'}")
    print("-" * 50)
    overall_total = 0
    overall_pass = 0
    any_fail = 0

    for name in entries:
        report = load_report(os.path.join(dir_path, name))
        if not report:
            print(f"{name:<20} ----  -----  INVALID REPORT")
            continue
        suite = report.get("suite_name") or os.path.splitext(name)[0]
        total = int(report.get("summary", {}).get("total", 0))
        passed = int(report.get("summary", {}).get("passed", 0))
        result = "OK" if passed == total and total > 0 and report.get("compilation", {}).get("ok", True) else "FAIL"

        print(f"{suite:<20} {passed:>4} {total:>5} {result}")

        overall_total += total
        overall_pass += passed
        if result != "OK":
            any_fail = 1

    print("-" * 50)
    print(f"{'TOTAL':<20} {overall_pass:>4} {overall_total:>5} {'OK' if any_fail == 0 else 'HAS-FAIL'}")
    return 0 if any_fail == 0 else 1

def run_suite(
    suite_name: str,
    src: str,
    tests_path: str,
    bin_out: str,
    cflags: str,
    timeout: float,
    strip_mode: str,
    normalize_newlines: bool,
    case_sensitive: bool
) -> dict:
    """Compile then run all tests; return a structured report dict."""
    # Compilation
    if not os.path.exists(src):
        raise SystemExit(f"Source file not found: {src}")

    comp_err = compile_c(src, bin_out, cflags)
    report = {
        "suite_name": suite_name,
        "compilation": {
            "ok": comp_err is None,
            "error": comp_err or ""
        },
        "tests": [],
        "summary": {
            "total": 0,
            "passed": 0,
        }
    }

    # If compilation failed, return immediately (no tests executed)
    if comp_err is not None:
        return report

    # Load tests and execute
    tests = read_tests(tests_path)
    total = len(tests)
    passed = 0
    for t in tests:
        name = t["name"]
        stdin_data = t["stdin"]
        expected_field: Union[str, List[str]] = t["expected"]
        exp_exit = int(t.get("exit_code", 0))
        strip = t.get("strip", strip_mode)

        expected_list = expected_field if isinstance(expected_field, list) else [expected_field]
        expected_norm = [normalize(e, strip, normalize_newlines) for e in expected_list]

        try:
            proc = run_one(bin_out, stdin_data, timeout)
            out = proc.stdout
            err = proc.stderr
            code = proc.returncode
        except subprocess.TimeoutExpired:
            report["tests"].append({
                "name": name,
                "status": "TIMEOUT",
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "details": f"Timeout after {timeout}s"
            })
            continue

        got_norm = normalize(out, strip, normalize_newlines)
        if not case_sensitive:
            got_cmp = got_norm.lower()
            candidates = [e.lower() for e in expected_norm]
        else:
            got_cmp = got_norm
            candidates = expected_norm

        ok_out = (got_cmp in candidates)
        ok_code = (code == exp_exit)
        ok = ok_out and ok_code

        if ok:
            passed += 1
            report["tests"].append({
                "name": name,
                "status": "PASS",
                "exit_code": code,
                "stdout": out,
                "stderr": err
            })
        else:
            exp0 = expected_norm[0] if expected_norm else ""
            ref_exp = exp0 if case_sensitive else exp0.lower()
            diff_txt = diff_block(ref_exp, got_cmp)
            report["tests"].append({
                "name": name,
                "status": "FAIL",
                "exit_code": code,
                "stdout": out,
                "stderr": err,
                "details": {
                    "reason": f"Output match: {ok_out}, Exit code match: {ok_code} (expected {exp_exit}, got {code})",
                    "diff": diff_txt
                }
            })

    report["summary"]["total"] = total
    report["summary"]["passed"] = passed
    return report

def main():
    parser = argparse.ArgumentParser(
        description="Compile a C file with gcc and run stdin-based tests from JSON. Also supports cross-student summary."
    )
    # Mode A: run one suite (student)
    parser.add_argument("--suite-name", default="suite", help="Label shown in reports (e.g., student folder name)")
    parser.add_argument("--src", help="Path to C source file")
    parser.add_argument("--tests", help="Path to JSON tests file")
    parser.add_argument("--bin", default=os.environ.get("BIN_OUT", "/work/a.out"), help="Output binary path")
    parser.add_argument("--cflags", default=os.environ.get("CFLAGS", "-O2 -std=c17 -Wall -Wextra"),
                        help='CFLAGS passed to gcc')
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-test timeout (seconds)")
    parser.add_argument("--strip", choices=["none","left","right","both"], default="right",
                        help="Whitespace normalization for comparison (default: right)")
    parser.add_argument("--normalize-newlines", action="store_true",
                        help="Normalize CRLF/CR to LF before comparison")
    parser.add_argument("--case-sensitive", action="store_true",
                        help="Enable case-sensitive comparison")

    parser.add_argument("--report", help="Write a JSON report to this path (e.g., /work/reports/stu1.json)")

    # Mode B: summarize directory of JSON reports
    parser.add_argument("--summarize-dir", help="If set, read *.json in this dir and print summary table")

    args = parser.parse_args()

    # Summary-only mode
    if args.summarize_dir:
        sys.exit(summarize_dir(args.summarize_dir))

    # Run-one-suite mode requires src & tests
    if not args.src or not args.tests:
        parser.error("--src and --tests are required unless using --summarize-dir")

    report = run_suite(
        suite_name=args.suite_name,
        src=args.src,
        tests_path=args.tests,
        bin_out=args.bin,
        cflags=args.cflags,
        timeout=args.timeout,
        strip_mode=args.strip,
        normalize_newlines=args.normalize_newlines,
        case_sensitive=args.case_sensitive
    )

    # Human-readable console tail
    print(f"\n=== SUITE: {report['suite_name']} ===")
    comp_ok = report["compilation"]["ok"]
    if not comp_ok:
        print("✘ COMPILATION FAILED")
        print(report["compilation"]["error"])
        # Write report if requested, exit code 1 for failure
        if args.report:
            write_report(args.report, report)
        sys.exit(1)

    total = report["summary"]["total"]
    passed = report["summary"]["passed"]
    for t in report["tests"]:
        mark = "✔" if t["status"] == "PASS" else ("⏱" if t["status"] == "TIMEOUT" else "✘")
        print(f"{mark} {t['name']}: {t['status']}")
        if t["status"] != "PASS" and "details" in t:
            details = t["details"]
            if isinstance(details, dict):
                reason = details.get("reason", "")
                diff = details.get("diff")
                if reason:
                    print("  - " + reason)
                if diff:
                    print(textwrap.indent(diff, "    "))
            else:
                print("  - " + str(details))

    print(f"Passed {passed}/{total} tests")

    # Persist report if requested
    if args.report:
        write_report(args.report, report)

    # Exit code: 0 only when all pass
    sys.exit(0 if passed == total else 1)

if __name__ == "__main__":
    main()
