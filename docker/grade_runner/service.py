# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import subprocess
from typing import List, Optional, Tuple, Union

from .compile_helpers import (
    collect_sources_with_single_main,
    compile_c_multi,
    compile_c_single,
    read_submission_meta,
    run_make,
)
from .harness import diff_block, normalize, read_tests, run_one
from .models import Config
from .reporting import write_report


class RunnerService:
    """Orchestrates compile → run → report, preserving legacy behavior."""

    def run_suite(self, cfg: Config) -> dict:
        # Compilation
        comp_ok = False
        comp_err: Optional[str] = None

        include_dirs: List[str] = []
        c_files: List[str] = []

        if cfg.has_multi_file:
            if not os.path.isdir(cfg.src_dir):
                raise SystemExit(f"Source directory not found: {cfg.src_dir}")
            include_dirs.append(cfg.src_dir)

            if cfg.allow_make and os.path.isfile(os.path.join(cfg.src_dir, "Makefile")):
                rc, out, err = run_make(cfg.src_dir, env=None)
                comp_ok = (rc == 0)
                comp_err = None if comp_ok else (out + "\n" + err)
                if comp_ok and not os.path.exists(cfg.bin_out):
                    guess = os.path.join(cfg.src_dir, "a.out")
                    if os.path.exists(guess):
                        os.makedirs(os.path.dirname(cfg.bin_out), exist_ok=True)
                        try:
                            import shutil
                            shutil.copy2(guess, cfg.bin_out)
                        except Exception as e:
                            comp_ok = False
                            comp_err = f"Build succeeded but cannot stage binary: {e}"
                    else:
                        comp_ok = False
                        comp_err = f"Build succeeded but binary not found at {cfg.bin_out}"
            else:
                # Only include designated main + non-main .c files
                c_files = collect_sources_with_single_main(cfg.src_dir, cfg.main_filename, recursive=cfg.recursive)
                if not c_files:
                    comp_err = (f"Main file '{cfg.main_filename}' not found under {cfg.src_dir} "
                                f"or no .c sources available.")
                else:
                    comp_err = compile_c_multi(c_files, include_dirs, cfg.bin_out, cfg.cflags)
                comp_ok = (comp_err is None)

        else:
            # Single-file mode
            if not cfg.src or not os.path.exists(cfg.src):
                raise SystemExit(f"Source file not found: {cfg.src}")
            comp_err = compile_c_single(cfg.src, cfg.bin_out, cfg.cflags)
            comp_ok = (comp_err is None)

        # Read submission meta and record selected main
        submission_meta = {}
        root_for_meta = cfg.src_dir if cfg.src_dir else (os.path.dirname(cfg.src) if cfg.src else None)
        if root_for_meta and os.path.isdir(root_for_meta):
            submission_meta = read_submission_meta(root_for_meta) or {}
        submission_meta.setdefault("selected_main", cfg.main_filename)

        report = {
            "suite_name": cfg.suite_name,
            "compilation": {
                "ok": comp_ok,
                "error": comp_err or "",
            },
            "tests": [],
            "summary": {
                "total": 0,
                "passed": 0,
            },
            "submission": submission_meta,
        }

        # Stop if compilation failed
        if not comp_ok:
            return report

        # Load tests
        tests = read_tests(cfg.tests_path) if cfg.tests_path else []
        total = len(tests)
        passed = 0

        for t in tests:
            name = t["name"]
            stdin_data = t["stdin"]
            expected_field: Union[str, List[str]] = t["expected"]
            exp_exit = int(t.get("exit_code", 0))
            strip = t.get("strip", cfg.strip_mode)

            expected_list = expected_field if isinstance(expected_field, list) else [expected_field]
            expected_norm = [normalize(e, strip, cfg.normalize_newlines) for e in expected_list]

            try:
                proc = run_one(cfg.bin_out, stdin_data, cfg.timeout)
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
                    "details": f"Timeout after {cfg.timeout}s",
                })
                continue
            except Exception as e:
                report["tests"].append({
                    "name": name,
                    "status": "ERROR",
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "details": f"Error running test: {e}",
                })
                continue

            got_norm = normalize(out, strip, cfg.normalize_newlines)
            if not cfg.case_sensitive:
                got_cmp = got_norm.lower()
                candidates = [e.lower() for e in expected_norm]
            else:
                got_cmp = got_norm
                candidates = expected_norm

            # --- regex based compare ---
            ok_out = False
            for pattern in candidates:
                try:
                    if re.fullmatch(pattern, got_cmp, re.DOTALL):
                        ok_out = True
                        break
                except re.error as regex_err:
                    pass

            ok_code = (code == exp_exit)
            ok = ok_out and ok_code

            if ok:
                passed += 1
                report["tests"].append({
                    "name": name,
                    "status": "PASS",
                    "exit_code": code,
                    "stdout": out,
                    "stderr": err,
                })
            else:
                exp0 = expected_norm[0] if expected_norm else ""
                ref_exp = exp0 if cfg.case_sensitive else exp0.lower()
                diff_txt = diff_block(ref_exp, got_cmp)
                report["tests"].append({
                    "name": name,
                    "status": "FAIL",
                    "exit_code": code,
                    "stdout": out,
                    "stderr": err,
                    "details": {
                        "reason": f"Output match: {ok_out}, Exit code match: {ok_code} (expected {exp_exit}, got {code})",
                        "diff": diff_txt,
                    },
                })

        report["summary"]["total"] = total
        report["summary"]["passed"] = passed
        return report
