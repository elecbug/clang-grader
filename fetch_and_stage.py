#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import re
import sys
import time
import hashlib
import unicodedata
import requests
from typing import Tuple, Optional, List, Dict
from urllib.parse import urlsplit, urlunsplit, unquote, quote
from datetime import datetime, timezone

# ---------------------------
# Regex for GitHub URL forms
# ---------------------------
BLOB_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/blob/(?P<branch>[^/]+)/(?P<path>.+)$"
)
RAW_RE = re.compile(
    r"^https?://raw\.githubusercontent\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<branch>[^/]+)/(?P<path>.+)$"
)

# ---------------------------
# Helpers
# ---------------------------
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
    url = _nfkc(url).strip()
    parts = urlsplit(url)
    clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    m = BLOB_RE.match(clean_url)
    if m:
        owner  = m.group("owner")
        repo   = m.group("repo")
        branch = m.group("branch")
        path   = m.group("path")
        path_enc = _encode_path_preserving_segments(path)
        raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path_enc}"
        filename = os.path.basename(unquote(path))
        return owner, repo, branch, path, raw, filename

    m = RAW_RE.match(clean_url)
    if m:
        owner  = m.group("owner")
        repo   = m.group("repo")
        branch = m.group("branch")
        path   = m.group("path")
        path_enc = _encode_path_preserving_segments(path)
        raw_norm = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path_enc}"
        filename = os.path.basename(unquote(path))
        return owner, repo, branch, path, raw_norm, filename

    if "github.com" in clean_url:
        raise ValueError(f"Unsupported GitHub URL shape: {url}")
    raise ValueError(f"Unrecognized GitHub URL: {url}")

def fetch_raw(url: str, token: Optional[str], max_retries: int = 5) -> bytes:
    """Fetch raw file bytes with optional token and backoff."""
    headers = {"Accept": "application/vnd.github.v3.raw"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    backoff = 1.0
    for _ in range(max_retries):
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

def gh_get(url: str, token: Optional[str], params: Optional[dict] = None, accept: str = "application/vnd.github+json"):
    """GET helper for GitHub API with token/backoff."""
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    backoff = 1.0
    while True:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            return resp
        if resp.status_code in (403, 429):
            reset = resp.headers.get("X-RateLimit-Reset")
            if reset and reset.isdigit():
                sleep_s = max(0, int(reset) - int(time.time()) + 1)
            else:
                sleep_s = backoff
            time.sleep(sleep_s)
            backoff = min(backoff * 2, 60)
            continue
        raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:200]}")

# ---------------------------
# Commit / tree lookup
# ---------------------------
def get_repo_commit_before(owner: str, repo: str, branch: str, limit_dt: datetime, token: Optional[str]) -> Optional[str]:
    """
    Return the repository HEAD commit sha on the given branch whose committer date <= limit_dt (UTC).
    We page through history until we find the first <= limit date.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    params = {"sha": branch, "per_page": 100}
    while True:
        resp = gh_get(url, token, params=params)
        commits = resp.json()
        if not commits:
            return None
        for c in commits:
            ts = c["commit"]["committer"]["date"]  # ISO8601 with 'Z'
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            if dt <= limit_dt:
                return c["sha"]
        # older pages
        if "next" in resp.links:
            url = resp.links["next"]["url"]
            params = None
            continue
        return None

def list_tree_c_h_paths(owner: str, repo: str, commit_sha: str, token: Optional[str], scope_prefix: Optional[str]) -> List[str]:
    """
    List all .c / .h file paths at the given commit. If scope_prefix is given,
    only return paths under that prefix (directory scope).
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{commit_sha}"
    resp = gh_get(url, token, params={"recursive": "1"})
    data = resp.json()
    if "tree" not in data:
        raise RuntimeError("Malformed tree response")
    paths: List[str] = []
    for ent in data["tree"]:
        if ent.get("type") != "blob":
            continue
        p = ent.get("path", "")
        if scope_prefix and not (p == scope_prefix or p.startswith(scope_prefix.rstrip("/") + "/")):
            continue
        if p.lower().endswith((".c", ".h")):
            paths.append(p)
    return paths

# ---------------------------
# IO helpers
# ---------------------------
def safe_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)

# ---------------------------
# Main
# ---------------------------
def main():
    ap = argparse.ArgumentParser(description="Fetch C/H sources from GitHub and stage per-student directories.")
    ap.add_argument("--map", required=True, help="Path to student map JSON (list or {limit, students}).")
    ap.add_argument("--suite", required=True, help="Suite name (staged under data/<suite>/).")
    ap.add_argument("--data-root", default="data", help="Root data directory (default: data).")
    ap.add_argument("--rename-to", default="main.c",
                    help="If representative file's basename differs, also save a copy as this name at student root (default: main.c).")
    ap.add_argument("--keep-original", action="store_true", help="Also save representative file with its original filename at student root.")
    ap.add_argument("--hash-check", action="store_true", help="Skip download if representative file hash unchanged (still downloads others).")
    ap.add_argument("--respect-limit", action="store_true", help="Respect 'limit' field in map JSON (ISO 8601).")
    ap.add_argument("--scope", choices=["repo", "dir"], default="repo",
                    help="Fetch scope: whole repo (repo) or only under the representative file's directory (dir). Default: repo.")
    ap.add_argument("--preserve-subdirs", action="store_true", default=True,
                    help="Preserve the original subdirectory structure under student's folder.")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "").strip() or None
    with open(args.map, "r", encoding="utf-8") as f:
        map_data = json.load(f)

    # Resolve limit and students list
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
    staged_students = 0

    for it in students:
        stu = it.get("id")
        url = it.get("url")
        if not stu or not url:
            continue

        # Parse representative URL (usually the problem file)
        try:
            owner, repo, branch, path, raw_url, guessed = to_raw_parts(url)
        except Exception as e:
            print(f"[{stu}] URL parsing failed: {e}", file=sys.stderr)
            continue

        # Determine commit sha
        if limit_dt is not None:
            try:
                commit_sha = get_repo_commit_before(owner, repo, branch, limit_dt, token)
            except Exception as e:
                print(f"[{stu}] commit lookup failed: {e}", file=sys.stderr)
                commit_sha = None
            if not commit_sha:
                print(f"[{stu}] No commit on branch '{branch}' before {limit_dt.isoformat()}, skipping.")
                continue
            print(f"[{stu}] Using repo commit {commit_sha} (<= {limit_dt.isoformat()})")
        else:
            # Use branch HEAD
            try:
                resp = gh_get(f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}", token)
                commit_sha = resp.json()["sha"]
                print(f"[{stu}] Using branch HEAD {commit_sha}")
            except Exception as e:
                print(f"[{stu}] HEAD lookup failed: {e}", file=sys.stderr)
                continue

        # Decide scope prefix (for dir-scope mode)
        rep_dir_prefix = os.path.dirname(unquote(path))
        scope_prefix = None
        if args.scope == "dir":
            scope_prefix = rep_dir_prefix if rep_dir_prefix else None

        # List .c/.h paths at the commit
        try:
            paths = list_tree_c_h_paths(owner, repo, commit_sha, token, scope_prefix)
        except Exception as e:
            print(f"[{stu}] tree list failed: {e}", file=sys.stderr)
            continue

        if not paths:
            print(f"[{stu}] No .c/.h files found at commit {commit_sha} (scope={args.scope}).")
            continue

        # Stage all .c/.h files under student's directory (preserve subdirs)
        staged_count = 0
        for p in paths:
            p_enc = _encode_path_preserving_segments(p)
            raw_p = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_sha}/{p_enc}"
            try:
                data = fetch_raw(raw_p, token)
            except Exception as e:
                print(f"[{stu}] fetch failed for {p}: {e}", file=sys.stderr)
                continue

            if args.preserve_subdirs:
                local_path = os.path.join(suite_dir, stu, p)  # keep original subdir
            else:
                # flatten into student root
                local_path = os.path.join(suite_dir, stu, os.path.basename(unquote(p)))

            safe_write(local_path, data)
            staged_count += 1

        # Optionally duplicate the representative file as main.c at student root
        rep_basename = os.path.basename(unquote(path))
        if args.rename_to and rep_basename.lower() != args.rename_to.lower():
            # Fetch the representative file at the chosen commit and copy as rename_to
            rep_path_for_raw = _encode_path_preserving_segments(unquote(path))
            rep_raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_sha}/{rep_path_for_raw}"
            try:
                rep_data = fetch_raw(rep_raw_url, token)
                main_target = os.path.join(suite_dir, stu, args.rename_to)
                safe_write(main_target, rep_data)
                if args.keep_original:
                    orig_target = os.path.join(suite_dir, stu, rep_basename)
                    # If not already saved at root, write a copy
                    if not os.path.exists(orig_target):
                        safe_write(orig_target, rep_data)
            except Exception as e:
                print(f"[{stu}] failed to save representative as {args.rename_to}: {e}", file=sys.stderr)

        print(f"[{stu}] staged {staged_count} files under {os.path.join(suite_dir, stu)}")
        staged_students += 1

    print(f"Staged students: {staged_students}, Suite: {args.suite}, Root: {suite_dir}")

if __name__ == "__main__":
    main()
