# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import sys
import textwrap

from grade_runner.models import Config
from grade_runner.reporting import summarize_dir, write_report
from grade_runner.service import RunnerService


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Compile a C submission and run stdin-based tests from JSON.")

    # Modes
    p.add_argument("--suite-name", default="suite", help="Label in reports (e.g., student folder name)")

    # Single-file mode
    p.add_argument("--src", help="Path to C source file")

    # Multi-file mode
    p.add_argument("--src-dir", help="Path to a directory containing C sources/headers")
    p.add_argument("--no-recursive", action="store_true", help="Do not search subdirectories")
    p.add_argument("--allow-make", action="store_true", help="If Makefile exists under src-dir, run 'make' instead of gcc")

    # Build & run
    p.add_argument("--tests", help="Path to JSON tests file")
    p.add_argument("--bin", dest="bin_out", default=os.environ.get("BIN_OUT", "/work/a.out"), help="Output binary path")
    p.add_argument("--cflags", default=os.environ.get("CFLAGS", "-O2 -std=c17 -Wall -Wextra"), help="CFLAGS passed to gcc")
    p.add_argument("--timeout", type=float, default=2.0, help="Per-test timeout (seconds)")
    p.add_argument("--strip", choices=["none", "left", "right", "both"], default="right", help="Whitespace normalization (default: right)")
    p.add_argument("--normalize-newlines", action="store_true", help="Normalize CRLF/CR to LF before comparison")
    p.add_argument("--case-sensitive", action="store_true", help="Enable case-sensitive comparison")

    # Reporting
    p.add_argument("--report", dest="report_path", help="Write a JSON report to this path (e.g., /work/reports/stu1.json)")
    p.add_argument("--summarize-dir", help="Read *.json in this dir and print summary table")
    p.add_argument("--main-filename", default="main.c", help="Representative main source filename to include (default: main.c)")

    return p


def main() -> None:
    parser = build_argparser()
    args = parser.parse_args()

    # Summary-only mode
    if args.summarize_dir:
        sys.exit(summarize_dir(args.summarize_dir))

    # Require either src or src-dir
    if not args.src and not args.src_dir:
        parser.error("Either --src or --src-dir must be provided.")

    cfg = Config(
        suite_name=args.suite_name,
        src=args.src,
        src_dir=args.src_dir,
        recursive=(not args.no_recursive),
        allow_make=args.allow_make,
        tests_path=args.tests,
        bin_out=args.bin_out,
        cflags=args.cflags,
        timeout=args.timeout,
        strip_mode=args.strip,
        normalize_newlines=args.normalize_newlines,
        case_sensitive=args.case_sensitive,
        main_filename=args.main_filename,
        report_path=args.report_path,
        summarize_dir=args.summarize_dir,
    )

    service = RunnerService()
    report = service.run_suite(cfg)

    # Human-readable console (kept identical to legacy style)
    print(f"\n=== SUITE: {report['suite_name']} ===")
    comp_ok = report["compilation"]["ok"]
    if not comp_ok:
        print("✘ COMPILATION FAILED")
        print(report["compilation"]["error"])
        if cfg.report_path:
            write_report(cfg.report_path, report)
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

    if cfg.report_path:
        write_report(cfg.report_path, report)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()