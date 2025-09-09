# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from typing import Optional


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