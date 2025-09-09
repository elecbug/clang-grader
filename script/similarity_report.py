#!/usr/bin/env python3
import os
import re
import sys
import difflib
import json
from typing import Dict, Tuple

def preprocess_code(code: str) -> str:
    """Remove comments/whitespace and normalize code string."""
    # Remove /* ... */ block comments
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    # Remove // line comments
    code = re.sub(r"//.*", "", code)
    # Collapse whitespace
    code = re.sub(r"\s+", " ", code)
    return code.strip()

def read_main_hint(student_dir: str) -> str:
    """Read .main_filename if present; default to 'main.c'."""
    hint_path = os.path.join(student_dir, ".main_filename")
    if os.path.isfile(hint_path):
        try:
            with open(hint_path, "r", encoding="utf-8") as f:
                # Strip CR/LF and trailing spaces
                name = f.read().strip()
                if name:
                    return name
        except Exception as e:
            print(f"[WARN] {student_dir}: failed to read .main_filename - {e}", file=sys.stderr)
    return "main.c"

def load_codes(root_dir: str) -> Dict[str, str]:
    """
    Load representative main codes using .main_filename hint (or main.c fallback).
    Only compares the specified main file per student.
    """
    codes: Dict[str, str] = {}
    if not os.path.isdir(root_dir):
        print(f"[ERROR] Not a directory: {root_dir}", file=sys.stderr)
        return codes

    for stu_id in sorted(os.listdir(root_dir)):
        student_dir = os.path.join(root_dir, stu_id)
        if not os.path.isdir(student_dir):
            continue

        # Decide main path from hint
        main_rel = read_main_hint(student_dir)  # may include subdirs
        main_path = os.path.join(student_dir, main_rel)

        # Fallback to main.c at root if hinted file does not exist
        if not os.path.isfile(main_path):
            fallback = os.path.join(student_dir, "main.c")
            if os.path.isfile(fallback):
                print(f"[INFO] {stu_id}: hinted main '{main_rel}' not found; using fallback 'main.c'", file=sys.stderr)
                main_path = fallback
            else:
                print(f"[WARN] {stu_id}: no main file found (hint='{main_rel}', no fallback). Skipped.", file=sys.stderr)
                continue

        try:
            with open(main_path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            codes[stu_id] = preprocess_code(raw)
        except Exception as e:
            print(f"[WARN] {stu_id}: failed to read '{os.path.relpath(main_path, student_dir)}' - {e}", file=sys.stderr)

    return codes

def similarity(a: str, b: str) -> float:
    """Compute similarity ratio between two code strings (0~1)."""
    return difflib.SequenceMatcher(None, a, b).ratio()

def build_report(codes: Dict[str, str]) -> Dict[str, dict]:
    """Return dict: student -> {best_match, score} comparing only representative mains."""
    report: Dict[str, dict] = {}
    stu_ids = list(codes.keys())
    for sid in stu_ids:
        code = codes[sid]
        best_peer = None
        best_score = -1.0
        for other_id in stu_ids:
            if sid == other_id:
                continue
            sim = similarity(code, codes[other_id])
            if sim > best_score:
                best_score = sim
                best_peer = other_id
        report[sid] = {
            "best_match": best_peer,
            "score": round(best_score, 3) if best_peer is not None else None
        }
    return report

def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Compute similarity among students by comparing ONLY their representative main files."
    )
    ap.add_argument("root_dir", help="Root dir containing <student_id>/... and .main_filename hints")
    ap.add_argument("-o", "--out", default="similarity_report.json",
                    help="Output report JSON (default: similarity_report.json)")
    args = ap.parse_args()

    codes = load_codes(args.root_dir)
    if not codes:
        print("No comparable codes found under", args.root_dir)
        sys.exit(1)

    report = build_report(codes)

    # Save JSON report
    try:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Report saved to {args.out}")
    except Exception as e:
        print(f"[ERROR] Failed to write report: {e}", file=sys.stderr)
        sys.exit(2)

    # Console summary
    for sid, info in report.items():
        print(f"{sid}: best match → {info['best_match']} (score={info['score']})")

if __name__ == "__main__":
    main()
