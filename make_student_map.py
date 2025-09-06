#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Parse a pasted table-like text (e.g., exported from Excel) that contains columns like:
  연번, 학과명, 성명, 아이디, 제출여부, ..., 과제설명
and build a student_map.json:
{
  "limit": "2025-09-09T00:00:00Z",   # optional if --limit provided
  "students": [
    {"id":"5880642", "url":"https://github.com/.../blob/.../ex01.c"},
    ...
  ]
}

Key features:
- Normalizes full-width characters (NFKC) and weird spaced schemes like "ＨＴＴＰＳ ://"
- Extracts GitHub URLs from the "assignment description" field even if it spans multiple lines
- By default, only keeps GitHub links that look like a code file (.c/.cpp) under blob/raw
- CLI options allow including non-file URLs, filtering to only "제출" rows, etc.
"""

import argparse
import json
import re
import sys
import unicodedata
from typing import List, Dict, Tuple, Optional

# --- Regex helpers -----------------------------------------------------------

# After normalization we still forgive stray spaces after scheme, e.g. "https ://"
SCHEME_FIX_RE = re.compile(r'\b(https?)\s*:\s*//', re.IGNORECASE)

# Match GitHub URLs robustly (blob/raw/tree allowed; we will filter later)
GITHUB_URL_RE = re.compile(
    r'(https?://(?:www\.)?github\.com/[^\s]+)', re.IGNORECASE
)

# Simple integer-ish ID (7+ digits typical in your sheet)
ID_RE = re.compile(r'\b\d{6,}\b')

# File extension filter (default policy keeps C/C++ files only)
CODE_EXT_RE = re.compile(r'\.(?:c|cpp|cc|cxx|h|hpp)$', re.IGNORECASE)

# Blob/raw markers
BLOB_OR_RAW_RE = re.compile(r'/(blob|raw)/', re.IGNORECASE)


# --- Core functions ----------------------------------------------------------

def normalize_text(s: str) -> str:
    """Normalize full-width ASCII etc. and collapse scheme spaces."""
    # Unicode NFKC handles full-width → ASCII (Ｈ→H, ：→:)
    s = unicodedata.normalize('NFKC', s)
    # Fix "https ://" → "https://"
    s = SCHEME_FIX_RE.sub(r'\1://', s)
    return s


def split_rows(raw: str) -> List[str]:
    """
    Heuristic row splitter:
    - Many exports are TSV/CSV-like but wrapped.
    - We split by newline, yet we later reconstruct per student by scanning for '아이디' then hoovering subsequent lines until next id.
    More stable: group lines into records keyed by the *latest ID seen*.
    """
    lines = [ln.rstrip() for ln in raw.splitlines()]
    return lines


def harvest_records(lines: List[str]) -> Dict[str, List[str]]:
    """
    Group contiguous lines to a record bucket keyed by a student ID.
    If a line contains a new ID, start a new bucket.
    """
    buckets: Dict[str, List[str]] = {}
    current_id: Optional[str] = None

    for ln in lines:
        ids = ID_RE.findall(ln)
        # If a line has exactly one new ID and it's not the same as current, start new record.
        if ids:
            # Choose the first plausible ID; if multiple, pick the last 7+ digits token.
            sid = ids[-1]
            if current_id != sid:
                current_id = sid
                buckets.setdefault(current_id, [])
        if current_id is not None:
            buckets[current_id].append(ln)

    return buckets


def extract_submission_flag(record_text: str) -> Optional[bool]:
    """
    Try to decide if this record is a submitted one.
    Returns True/False/None (unknown).
    """
    # Look for "제출여부\t제출" or a standalone '제출' token near the header area.
    # Since the record text is a concatenation, this is heuristic.
    if "미제출" in record_text:
        return False
    if "제출" in record_text:
        return True
    return None


def extract_urls(record_text: str) -> List[str]:
    """Find GitHub URLs present in the record text."""
    # Replace spaces inside parentheses that sometimes break URLs
    # (We already normalized "https ://" → "https://")
    found = GITHUB_URL_RE.findall(record_text)
    # Clean trailing punctuation
    cleaned = []
    for url in found:
        url = url.strip().strip(')];,\'"）』」〉>…')
        # Some exports insert spaces inside the path. Remove internal spaces around slashes.
        url = re.sub(r'\s+/', '/', url)
        url = re.sub(r'/\s+', '/', url)
        cleaned.append(url)
    # Dedup while preserving order
    seen = set()
    uniq = []
    for u in cleaned:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def choose_best_url(urls: List[str], strict_code_only: bool) -> Optional[str]:
    """
    Choose the most likely source file URL.
    Preference:
      1) blob/raw + code extension (.c/.cpp/...)
      2) any blob/raw
      3) otherwise first GitHub URL (if strict_code_only=False)
    """
    # 1) blob/raw + code extension
    for u in urls:
        if BLOB_OR_RAW_RE.search(u) and CODE_EXT_RE.search(u):
            return u
    # 2) any blob/raw
    for u in urls:
        if BLOB_OR_RAW_RE.search(u):
            if not strict_code_only:
                return u
    # 3) first github url if allowed
    if not strict_code_only and urls:
        return urls[0]
    return None


def build_map(
    text: str,
    limit: Optional[str],
    only_submitted: bool,
    strict_code_only: bool
) -> Dict:
    """
    Convert full pasted table text → student_map dict.
    """
    norm = normalize_text(text)
    lines = split_rows(norm)
    buckets = harvest_records(lines)

    students: List[Dict[str, str]] = []
    seen_ids = set()
    seen_pairs = set()

    for sid, rec_lines in buckets.items():
        block = "\n".join(rec_lines)
        # Filter by '제출' if requested
        if only_submitted:
            flag = extract_submission_flag(block)
            if flag is False:
                continue

        urls = extract_urls(block)
        best = choose_best_url(urls, strict_code_only=strict_code_only)
        if not best:
            continue  # skip rows without a usable URL

        # Deduplicate
        if sid in seen_ids and (sid, best) in seen_pairs:
            continue
        seen_ids.add(sid)
        seen_pairs.add((sid, best))

        students.append({"id": sid, "url": best})

    out = {"students": students}
    if limit:
        out["limit"] = limit
    return out


# --- CLI ---------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Build student_map.json from pasted table text."
    )
    p.add_argument("input", nargs="?", default="-",
                   help="Input text file (default: stdin).")
    p.add_argument("-o", "--out", default="student_map.json",
                   help="Output JSON path (default: student_map.json).")
    p.add_argument("--limit", default=None,
                   help="ISO8601 timestamp for grading cutoff, e.g., 2025-09-09T00:00:00Z")
    p.add_argument("--only-submitted", action="store_true",
                   help="Keep only rows that look like '제출'.")
    p.add_argument("--include-nonfile", action="store_true",
                   help="Include non-file GitHub URLs (e.g., repo root/tree).")
    p.add_argument("--pretty", action="store_true",
                   help="Pretty-print JSON (indent=2).")

    args = p.parse_args()

    # Read input text
    if args.input == "-":
        raw = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            raw = f.read()

    student_map = build_map(
        text=raw,
        limit=args.limit,
        only_submitted=args.only_submitted,
        strict_code_only=(not args.include_nonfile),
    )

    # Write JSON
    with open(args.out, "w", encoding="utf-8") as f:
        if args.pretty:
            json.dump(student_map, f, ensure_ascii=False, indent=2)
        else:
            json.dump(student_map, f, ensure_ascii=False)

    print(f"Written: {args.out}  (students: {len(student_map.get('students', []))})")


if __name__ == "__main__":
    main()
