#!/usr/bin/env python3
import os
import re
import sys
import difflib
import itertools
import json

def preprocess_code(code: str) -> str:
    """Remove comments/whitespace and normalize code string."""
    # Remove /* ... */ block comments
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    # Remove // line comments
    code = re.sub(r"//.*", "", code)
    # Collapse whitespace
    code = re.sub(r"\s+", " ", code)
    return code.strip()

def load_codes(root_dir: str):
    """Load student codes from root_dir/<student_id>/main.c"""
    codes = {}
    for stu_id in os.listdir(root_dir):
        stu_path = os.path.join(root_dir, stu_id, "main.c")
        if os.path.isfile(stu_path):
            try:
                with open(stu_path, encoding="utf-8") as f:
                    raw = f.read()
                codes[stu_id] = preprocess_code(raw)
            except Exception as e:
                print(f"[WARN] {stu_id}: Fail to read file - {e}", file=sys.stderr)
    return codes

def similarity(a: str, b: str) -> float:
    """Compute similarity ratio between two code strings (0~1)."""
    return difflib.SequenceMatcher(None, a, b).ratio()

def build_report(codes: dict):
    """Return dict: student -> {best_match, score}"""
    report = {}
    for sid, code in codes.items():
        best_score = -1.0
        best_peer = None
        for other_id, other_code in codes.items():
            if sid == other_id:
                continue
            sim = similarity(code, other_code)
            if sim > best_score:
                best_score = sim
                best_peer = other_id
        report[sid] = {
            "best_match": best_peer,
            "score": round(best_score, 3) if best_peer else None
        }
    return report

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Compute pairwise similarity and report best match per student.")
    ap.add_argument("root_dir", help="Root directory containing <student_id>/main.c files")
    ap.add_argument("-o", "--out", default="similarity_report.json", help="Output report JSON (default: similarity_report.json)")
    args = ap.parse_args()

    codes = load_codes(args.root_dir)
    if not codes:
        print("No codes found under", args.root_dir)
        sys.exit(1)

    report = build_report(codes)

    # Save JSON report
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"Report saved to {args.out}")
    for sid, info in report.items():
        print(f"{sid}: best match → {info['best_match']} (score={info['score']})")

if __name__ == "__main__":
    main()
