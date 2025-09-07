#!/usr/bin/env python3
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
from typing import List, Union, Optional, Tuple

# -------------------------------
# Compile helpers
# -------------------------------

MAIN_PATTERN = re.compile(r'\bint\s+main\s*\(')

def is_main_file(path: str) -> bool:
    """Return True if the file contains a definition of int main(...)."""
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return bool(MAIN_PATTERN.search(f.read()))
    except Exception:
        # If unreadable, let the compiler handle; treat as non-main here.
        return False

def collect_sources_with_single_main(src_dir: str, main_filename: str, recursive: bool = True) -> List[str]:
    """
    Collect .c sources under src_dir such that only `main_filename` provides main().
    Any other .c that also defines main() will be skipped.
    """
    selected: List[str] = []
    main_path = os.path.join(src_dir, main_filename)
    if not os.path.isfile(main_path):
        # Caller decides whether to error out or fallback
        return selected

    # Always include the representative main
    selected.append(os.path.abspath(main_path))

    # Walk and gather non-main .c files
    if recursive:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for fn in files:
                if not fn.endswith(".c"):
                    continue
                full = os.path.abspath(os.path.join(root, fn))
                if full == os.path.abspath(main_path):
                    continue
                if is_main_file(full):
                    # Skip extra mains
                    print(f"[INFO] Skipping extra main in {full}")
                    continue
                selected.append(full)
    else:
        for fn in os.listdir(src_dir):
            if not fn.endswith(".c"):
                continue
            full = os.path.abspath(os.path.join(src_dir, fn))
            if full == os.path.abspath(main_path):
                continue
            if is_main_file(full):
                print(f"[INFO] Skipping extra main in {full}")
                continue
            selected.append(full)

    return selected

def find_c_files(src_dir: str, recursive: bool = True) -> List[str]:
    """Collect .c files under src_dir (recursive by default)."""
    c_files = []
    if recursive:
        for root, dirs, files in os.walk(src_dir):
            # Skip hidden dirs like .git
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for fn in files:
                if fn.endswith(".c"):
                    c_files.append(os.path.join(root, fn))
    else:
        for fn in os.listdir(src_dir):
            if fn.endswith(".c"):
                c_files.append(os.path.join(src_dir, fn))
    return c_files

def detect_multiple_mains(c_files: List[str]) -> Tuple[int, List[str]]:
    """Light-weight detection of multiple 'main' definitions to warn/fail early."""
    import re
    main_re = re.compile(r'\bint\s+main\s*\(')
    hits = []
    for f in c_files:
        try:
            with open(f, 'r', encoding='utf-8', errors='ignore') as fh:
                src = fh.read()
            if main_re.search(src):
                hits.append(f)
        except Exception:
            # If cannot read, ignore here; compiler will fail anyway
            pass
    return (len(hits), hits)

def run_make(src_dir: str, env: Optional[dict] = None) -> Tuple[int, str, str]:
    """Run 'make' in the student directory if requested."""
    proc = subprocess.run(
        ["make", "-C", src_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )
    return proc.returncode, proc.stdout, proc.stderr

def compile_c_single(src: str, bin_out: str, cflags: str) -> Optional[str]:
    """Compile single C source into an executable. Return stderr text on failure."""
    cmd = ["gcc"] + shlex.split(cflags) + ["-o", bin_out, src]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return (proc.stdout or "") + (proc.stderr or "")
    return None

def compile_c_multi(c_files: List[str], include_dirs: List[str], bin_out: str, cflags: str) -> Optional[str]:
    """Compile multiple C sources with include dirs."""
    cmd = ["gcc"] + shlex.split(cflags)
    for inc in include_dirs:
        cmd.extend(["-I", inc])
    cmd.extend(c_files)
    cmd.extend(["-o", bin_out])
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return (proc.stdout or "") + (proc.stderr or "")
    return None

# -------------------------------
# Test harness (unchanged core)
# -------------------------------

def read_tests(tests_path: str) -> List[dict]:
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
    return subprocess.run(
        [bin_path],
        input=stdin_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout
    )

def diff_block(expected: str, got: str) -> str:
    exp_vis = expected.replace("\n", "\\n\n")
    got_vis = got.replace("\n", "\\n\n")
    return textwrap.dedent(f"""
    --- expected ---
    {exp_vis}
    ---   got    ---
    {got_vis}
    """).rstrip()

def write_report(report_path: str, payload: dict) -> None:
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
    if not os.path.isdir(dir_path):
        print(f"Report directory not found: {dir_path}")
        return 1
    entries = sorted([p for p in os.listdir(dir_path) if p.endswith(".json")])
    if not entries:
        print(f"No reports found in {dir_path}")
        return 1

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
    src: Optional[str],
    src_dir: Optional[str],
    recursive: bool,
    allow_make: bool,
    tests_path: str,
    bin_out: str,
    cflags: str,
    timeout: float,
    strip_mode: str,
    normalize_newlines: bool,
    case_sensitive: bool,
    main_filename: str
) -> dict:
    """Compile then run all tests; return a structured report dict."""
    # Compilation
    comp_ok = False
    comp_err: Optional[str] = None

    # If src_dir is provided, prefer that path and compile all C files
    include_dirs: List[str] = []
    c_files: List[str] = []

    if src_dir:
        if not os.path.isdir(src_dir):
            raise SystemExit(f"Source directory not found: {src_dir}")
        include_dirs.append(src_dir)

        if allow_make and os.path.isfile(os.path.join(src_dir, "Makefile")):
            # 기존 Makefile 경로는 그대로 유지
            rc, out, err = run_make(src_dir, env=None)
            comp_ok = (rc == 0)
            comp_err = None if comp_ok else (out + "\n" + err)
            if comp_ok and not os.path.exists(bin_out):
                guess = os.path.join(src_dir, "a.out")
                if os.path.exists(guess):
                    os.makedirs(os.path.dirname(bin_out), exist_ok=True)
                    try:
                        import shutil
                        shutil.copy2(guess, bin_out)
                    except Exception as e:
                        comp_ok = False
                        comp_err = f"Build succeeded but cannot stage binary: {e}"
                else:
                    comp_ok = False
                    comp_err = f"Build succeeded but binary not found at {bin_out}"
        else:
            # New: only include designated main + non-main .c files
            c_files = collect_sources_with_single_main(src_dir, main_filename, recursive=recursive)

            if not c_files:
                comp_err = (f"Main file '{main_filename}' not found under {src_dir} "
                            f"or no .c sources available.")
            else:
                comp_err = compile_c_multi(c_files, include_dirs, bin_out, cflags)

            comp_ok = (comp_err is None)

    else:
        # Single-file mode
        if not src or not os.path.exists(src):
            raise SystemExit(f"Source file not found: {src}")
        comp_err = compile_c_single(src, bin_out, cflags)
        comp_ok = (comp_err is None)

    report = {
        "suite_name": suite_name,
        "compilation": {
            "ok": comp_ok,
            "error": comp_err or ""
        },
        "tests": [],
        "summary": {
            "total": 0,
            "passed": 0,
        }
    }

    # Stop if compilation failed
    if not comp_ok:
        return report

    # Load and run tests
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

# -------------------------------
# CLI
# -------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compile a C submission (single file or directory) and run stdin-based tests from JSON."
    )

    # Modes
    parser.add_argument("--suite-name", default="suite", help="Label in reports (e.g., student folder name)")

    # Single-file mode
    parser.add_argument("--src", help="Path to C source file")

    # Multi-file mode
    parser.add_argument("--src-dir", help="Path to a directory containing C sources/headers")
    parser.add_argument("--no-recursive", action="store_true", help="Do not search subdirectories")
    parser.add_argument("--allow-make", action="store_true", help="If Makefile exists under src-dir, run 'make' instead of gcc")

    parser.add_argument("--tests", help="Path to JSON tests file")
    parser.add_argument("--bin", default=os.environ.get("BIN_OUT", "/work/a.out"), help="Output binary path")
    parser.add_argument("--cflags", default=os.environ.get("CFLAGS", "-O2 -std=c17 -Wall -Wextra"),
                        help="CFLAGS passed to gcc")
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-test timeout (seconds)")
    parser.add_argument("--strip", choices=["none","left","right","both"], default="right",
                        help="Whitespace normalization for comparison (default: right)")
    parser.add_argument("--normalize-newlines", action="store_true",
                        help="Normalize CRLF/CR to LF before comparison")
    parser.add_argument("--case-sensitive", action="store_true",
                        help="Enable case-sensitive comparison")

    parser.add_argument("--report", help="Write a JSON report to this path (e.g., /work/reports/stu1.json)")
    parser.add_argument("--summarize-dir", help="Read *.json in this dir and print summary table")
    parser.add_argument("--main-filename", default="main.c",
                    help="Representative main source filename to include (default: main.c).")

    args = parser.parse_args()

    # Summary-only mode
    if args.summarize_dir:
        sys.exit(summarize_dir(args.summarize_dir))

    # Require either src or src-dir
    if not args.src and not args.src_dir:
        parser.error("Either --src or --src-dir must be provided.")

    # Run suite
    report = run_suite(
        suite_name=args.suite_name,
        src=args.src,
        src_dir=args.src_dir,
        recursive=(not args.no_recursive),
        allow_make=args.allow_make,
        tests_path=args.tests,
        bin_out=args.bin,
        cflags=args.cflags,
        timeout=args.timeout,
        strip_mode=args.strip,
        normalize_newlines=args.normalize_newlines,
        case_sensitive=args.case_sensitive,
        main_filename=args.main_filename
    )

    # Human-readable console
    print(f"\n=== SUITE: {report['suite_name']} ===")
    comp_ok = report["compilation"]["ok"]
    if not comp_ok:
        print("✘ COMPILATION FAILED")
        print(report["compilation"]["error"])
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

    if args.report:
        write_report(args.report, report)

    sys.exit(0 if passed == total else 1)

if __name__ == "__main__":
    main()
