#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
import hashlib
import unicodedata
import requests
from typing import Tuple, Optional
from urllib.parse import urlsplit, urlunsplit, unquote, quote
from datetime import datetime, timezone

BLOB_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/blob/(?P<branch>[^/]+)/(?P<path>.+)$"
)
RAW_RE = re.compile(
    r"^https?://raw\.githubusercontent\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<branch>[^/]+)/(?P<path>.+)$"
)

def _nfkc(s: str) -> str:
    """Normalize full-width characters to ASCII-compatible form."""
    return unicodedata.normalize("NFKC", s)

def _encode_path_preserving_segments(path: str) -> str:
    """
    Safely percent-encode a Git path:
    - Split on '/', unquote each segment (handles already-encoded Korean etc.)
    - Re-quote each segment so non-ASCII is encoded, slashes preserved.
    """
    segs = path.split("/")
    enc = [quote(unquote(seg), safe="") for seg in segs]
    return "/".join(enc)

def to_raw_parts(url: str):
    """
    Return (owner, repo, branch, path, raw_url, filename) with robust handling for
    non-ASCII (e.g., Korean) filenames and already percent-encoded paths.
    """
    # Normalize weird full-width characters (e.g., ＨＴＴＰＳ, ： )
    url = _nfkc(url).strip()

    # Strip query/fragment early; keep only scheme+netloc+path
    parts = urlsplit(url)
    clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    m = BLOB_RE.match(clean_url)
    if m:
        owner  = m.group("owner")
        repo   = m.group("repo")
        branch = m.group("branch")
        path   = m.group("path")  # may include Korean / spaces / () etc.

        # Encode path segments safely for raw.githubusercontent.com
        path_enc = _encode_path_preserving_segments(path)

        raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path_enc}"
        filename = os.path.basename(unquote(path))  # human-readable filename
        return owner, repo, branch, path, raw, filename

    m = RAW_RE.match(clean_url)
    if m:
        owner  = m.group("owner")
        repo   = m.group("repo")
        branch = m.group("branch")
        path   = m.group("path")

        # Normalize encoding to avoid mixed-encoding edge cases
        path_enc = _encode_path_preserving_segments(path)
        raw_norm = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path_enc}"
        filename = os.path.basename(unquote(path))
        return owner, repo, branch, path, raw_norm, filename

    # As a fallback, try parsing general github.com URL with urlsplit (rare paths)
    if "github.com" in clean_url:
        # Heuristic: expect /owner/repo/blob/<branch>/<path...> or raw domain
        # If different pattern, better to raise so caller can log the problematic link.
        raise ValueError(f"Unsupported GitHub URL shape: {url}")

    raise ValueError(f"Unrecognized GitHub URL: {url}")

def fetch_raw(url: str, token: Optional[str], max_retries: int = 5) -> bytes:
    headers = {"Accept": "application/vnd.github.v3.raw"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.content
        if resp.status_code in (403, 429):
            reset = resp.headers.get("X-RateLimit-Reset")
            if reset and reset.isdigit():
                sleep_s = max(0, int(reset) - int(time.time()) + 1)
            else:
                sleep_s = backoff
            time.sleep(sleep_s)
            backoff = min(backoff * 2, 60)
            continue
        raise RuntimeError(f"HTTP {resp.status_code} fetching {url}: {resp.text[:200]}")
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts")

def get_commit_before(owner, repo, branch, path, limit_dt: datetime, token: Optional[str]) -> Optional[str]:
    """Return commit sha of the last commit <= limit_dt for the given file."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    params = {"path": path, "sha": branch, "per_page": 50}
    while True:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to get commits: {resp.status_code} {resp.text}")
        commits = resp.json()
        if not commits:
            break
        chosen = None
        for c in commits:
            dt = datetime.fromisoformat(c["commit"]["committer"]["date"].replace("Z", "+00:00"))
            if dt <= limit_dt:
                chosen = c["sha"]
                return chosen
        # If all commits on this page are after limit, follow pagination
        if "next" in resp.links:
            url = resp.links["next"]["url"]
            params = None
            continue
        break
    return None

def safe_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)

def main():
    ap = argparse.ArgumentParser(description="Fetch C sources from GitHub and stage per-student directories.")
    ap.add_argument("--map", required=True, help="Path to student map JSON (with students list).")
    ap.add_argument("--suite", required=True, help="Suite name (staged under data/<suite>/).")
    ap.add_argument("--data-root", default="data", help="Root data directory (default: data).")
    ap.add_argument("--rename-to", default="main.c", help="Target filename in each student dir.")
    ap.add_argument("--keep-original", action="store_true", help="Also save original filename alongside main.c.")
    ap.add_argument("--hash-check", action="store_true", help="Skip download if hash unchanged.")
    ap.add_argument("--respect-limit", action="store_true", help="Respect 'limit' field in map JSON (ISO 8601).")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "").strip() or None
    with open(args.map, "r", encoding="utf-8") as f:
        map_data = json.load(f)

    limit_dt = None
    if args.respect_limit and isinstance(map_data, dict) and "limit" in map_data:
        limit_dt = datetime.fromisoformat(map_data["limit"].replace("Z", "+00:00")).astimezone(timezone.utc)
        students = map_data.get("students", [])
    elif isinstance(map_data, list):
        students = map_data
    elif isinstance(map_data, dict) and "students" in map_data:
        students = map_data["students"]
    else:
        print("Invalid map JSON format", file=sys.stderr)
        sys.exit(2)

    suite_dir = os.path.join(args.data_root, args.suite)
    staged = 0
    for it in students:
        stu = it.get("id")
        url = it.get("url")
        if not stu or not url:
            continue
        owner, repo, branch, path, raw_url, guessed = to_raw_parts(url)
        commit_sha = None
        if limit_dt is not None:
            try:
                commit_sha = get_commit_before(owner, repo, branch, path, limit_dt, token)
            except Exception as e:
                print(f"[{stu}] commit lookup failed: {e}", file=sys.stderr)
        if commit_sha:
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_sha}/{path}"
            print(f"[{stu}] Using commit {commit_sha} before {limit_dt.isoformat()}")
        else:
            if limit_dt:
                print(f"[{stu}] No commit before {limit_dt.isoformat()}, skipping.")
                continue
        data = fetch_raw(raw_url, token)
        target_dir = os.path.join(suite_dir, stu)
        target_main = os.path.join(target_dir, args.rename_to)
        safe_write(target_main, data)
        if args.keep_original and guessed != args.rename_to:
            safe_write(os.path.join(target_dir, guessed), data)
        print(f"[{stu}] saved {target_main}")
        staged += 1
    print(f"Staged: {staged}, Suite: {args.suite}, Root: {suite_dir}")

if __name__ == "__main__":
    main()
