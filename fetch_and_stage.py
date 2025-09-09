#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import requests
from typing import Tuple, Optional, List
from urllib.parse import urlsplit, urlunsplit, unquote, quote
from datetime import datetime, timezone

# ---------------------------
# Regex for GitHub URL forms
# ---------------------------
BLOB_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/blob/(?P<branch>[^/]+)/(?P<path>.+)$",
    re.IGNORECASE
)
RAW_RE = re.compile(
    r"^https?://raw\.githubusercontent\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<branch>[^/]+)/(?P<path>.+)$",
    re.IGNORECASE
)
TREE_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/tree/(?P<branch>[^/]+)(?:/(?P<path>.*))?$",
    re.IGNORECASE
)
REPO_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/?$",
    re.IGNORECASE
)

# ---------------------------
# Helpers
# ---------------------------

def _ensure_student_root(student_root: str) -> None:
    """Make sure the student's root directory exists."""
    os.makedirs(student_root, exist_ok=True)

def _write_submission_meta(student_root: str, meta: dict) -> None:
    """Append/merge submission meta sidecar to be consumed by run_tests.py."""
    _ensure_student_root(student_root)
    path = os.path.join(student_root, ".submission_meta.json")
    try:
        cur = {}
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                cur = json.load(f)
        cur.update(meta)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
    except Exception:
        # Do not block the pipeline on meta write failure
        pass

def _record_failure(student_root: str, stu: str, url: str, status: str, reason: str, detail: Optional[str] = None) -> None:
    """Standardize failure record and print a one-line console message."""
    payload = {
        "submitted_url": url,
        "status": status,          # e.g., 'url_parse_failed', 'default_branch_failed', ...
        "failure_reason": reason,
    }
    if detail:
        payload["detail"] = str(detail)[:500]
    _write_submission_meta(student_root, payload)
    print(f"[{stu}] ERROR {status}: {reason}")

def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)

def _encode_path_preserving_segments(path: str) -> str:
    segs = path.split("/")
    enc = [quote(unquote(seg), safe="") for seg in segs]
    return "/".join(enc)

def to_raw_parts(url: str):
    url = _nfkc(url).strip()
    parts = urlsplit(url)
    # Keep original path but drop query/fragment; matching is case-insensitive by regex flags
    clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    if clean_url.endswith(".git"):
        clean_url = clean_url[:-4]  # strip .git

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

    m = TREE_RE.match(clean_url)
    if m:
        owner  = m.group("owner")
        repo   = m.group("repo")
        branch = m.group("branch")
        path   = m.group("path") or ""   # may be None if tree root
        # For directories there is no single raw file URL or filename
        return owner, repo, branch, path, None, ""

    m = REPO_RE.match(clean_url)
    if m:
        owner = m.group("owner")
        repo  = m.group("repo")
        branch = None   # will be resolved by API (default_branch)
        path   = ""     # repo root
        return owner, repo, branch, path, None, ""

    if "github.com" in clean_url:
        raise ValueError(f"Unsupported GitHub URL shape: {url}")
    raise ValueError(f"Unrecognized GitHub URL: {url}")

def gh_get(url: str, token: Optional[str], params: Optional[dict] = None, accept: str = "application/vnd.github+json"):
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

def fetch_raw(url: str, token: Optional[str], max_retries: int = 5) -> bytes:
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

# ---------------------------
# Commit / tree / contents
# ---------------------------
def get_repo_commit_before(owner: str, repo: str, branch: str, limit_dt: datetime, token: Optional[str]) -> Optional[str]:
    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    params = {"sha": branch, "per_page": 100}
    while True:
        resp = gh_get(url, token, params=params)
        commits = resp.json()
        if not commits:
            return None
        for c in commits:
            ts = c["commit"]["committer"]["date"]
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            if dt <= limit_dt:
                return c["sha"]
        if "next" in resp.links:
            url = resp.links["next"]["url"]
            params = None
            continue
        return None

def get_branch_head(owner: str, repo: str, branch: str, token: Optional[str]) -> str:
    resp = gh_get(f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}", token)
    return resp.json()["sha"]

def list_tree_c_h_paths(owner: str, repo: str, commit_sha: str, token: Optional[str], scope_prefix: Optional[str]) -> List[str]:
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

def get_content_meta(owner: str, repo: str, path: str, ref: str, token: Optional[str]) -> Optional[dict]:
    """Return contents metadata for a path at ref. Keys: type ('file'/'dir'), path, name."""
    # API returns 200 for both file and directory; file → dict, dir → list
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{_encode_path_preserving_segments(unquote(path))}"
    try:
        resp = gh_get(url, token, params={"ref": ref})
    except Exception:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if isinstance(data, dict) and data.get("type") == "file":
        return {"type": "file", "path": data.get("path"), "name": data.get("name")}
    if isinstance(data, list):
        return {"type": "dir", "path": path, "name": os.path.basename(unquote(path))}
    return None

def get_default_branch(owner: str, repo: str, token: Optional[str]) -> str:
    """Return repository default_branch by API."""
    resp = gh_get(f"https://api.github.com/repos/{owner}/{repo}", token)
    data = resp.json()
    if "default_branch" not in data:
        raise RuntimeError("default_branch not found")
    return data["default_branch"]

# ---------------------------
# IO helpers
# ---------------------------
def safe_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)

# write main hint utility
def _write_main_hint(student_root: str, rel_main: str) -> None:
    """
    Write the chosen main filename (relative to src_dir) so run.sh can pass it to run_tests.py.
    Example values:
      - "main.c"
      - "Assignment/Assignment1/09.c"  (subdir allowed)
    """
    path = os.path.join(student_root, ".main_filename")
    os.makedirs(student_root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(rel_main.strip() + "\n")

MAIN_RE = re.compile(r'\bint\s+main\s*\(')

def _has_main_function(local_path: str) -> bool:
    """Return True if the local source contains a main() definition."""
    try:
        with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
            return bool(MAIN_RE.search(f.read()))
    except Exception:
        return False

def _pick_main_from_staged(student_root: str, scope_prefix: str, staged_paths: List[str], preserve_subdirs: bool) -> Optional[str]:
    """
    Decide representative main among staged .c files under a directory scope.
    Priority:
      1) '<scope_prefix>/main.c' if exists
      2) The unique .c that contains main()
    Returns a repo-relative path (matching staged relative layout) to write into .main_filename,
    or None if no clear choice.
    """
    # Normalize scope ('' means repo root)
    scope_prefix = (scope_prefix or "").strip("/")

    # If scope is repo root, consider all .c files; otherwise filter under the prefix
    if scope_prefix == "":
        c_paths = [p for p in staged_paths if p.lower().endswith(".c")]
    else:
        c_paths = [p for p in staged_paths if p.lower().endswith(".c") and
                   (p == scope_prefix or p.startswith(scope_prefix + "/"))]

    # 1) Prefer explicit main.c at the scope
    candidate_rel = f"{scope_prefix}/main.c" if scope_prefix else "main.c"
    local_main = os.path.join(student_root, candidate_rel)
    if os.path.isfile(local_main):
        return candidate_rel

    # 2) Otherwise, find the unique .c that defines main()
    main_candidates: List[str] = []
    for rel in c_paths:
        local_path = os.path.join(student_root, rel)
        if _has_main_function(local_path):
            main_candidates.append(rel)

    if len(main_candidates) == 1:
        return main_candidates[0]

    return None

# ---------------------------
# Main
# ---------------------------
def main():
    ap = argparse.ArgumentParser(description="Fetch C/H sources and the representative file from GitHub per student.")
    ap.add_argument("--map", required=True, help="Path to student map JSON (list or {limit, students}).")
    ap.add_argument("--suite", required=True, help="Suite name (staged under data/<suite>/).")
    ap.add_argument("--data-root", default="data", help="Root data directory (default: data).")
    ap.add_argument("--rename-to", default="main.c",
                    help="Also save representative file as this name at student root (default: main.c).")
    ap.add_argument("--keep-original", action="store_true",
                    help="Also save representative file with its original filename at student root.")
    ap.add_argument("--respect-limit", action="store_true",
                    help="Respect 'limit' field in map JSON (ISO 8601).")
    ap.add_argument("--scope", choices=["repo", "dir"], default="repo",
                    help="Fetch scope: whole repo or only under representative directory.")
    ap.add_argument("--preserve-subdirs", action="store_true", default=True,
                    help="Preserve original subdirectory structure when staging .c/.h.")
    ap.add_argument("--force-rename", action="store_true",
                help="Force saving representative file as rename-to even if it is a .c file. Default: False")

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

        try:
            owner, repo, branch, path, _, _ = to_raw_parts(url)
        except Exception as e:
            student_root = os.path.join(suite_dir, stu)
            _record_failure(
                student_root, stu, url,
                status="url_parse_failed",
                reason="Unrecognized or unsupported GitHub URL",
                detail=str(e),
            )
            continue

        if branch is None:
            # repository root URL → resolve default branch
            try:
                branch = get_default_branch(owner, repo, token)
                print(f"[{stu}] Using default branch '{branch}' (repo root URL)")
            except Exception as e:
                student_root = os.path.join(suite_dir, stu)
                _record_failure(
                    student_root, stu, url,
                    status="default_branch_failed",
                    reason="Could not resolve default branch",
                    detail=str(e),
                )
                continue

        student_root = os.path.join(suite_dir, stu)

        # Resolve commit
        if limit_dt is not None:
            try:
                commit_sha = get_repo_commit_before(owner, repo, branch, limit_dt, token)
            except Exception as e:
                student_root = os.path.join(suite_dir, stu)
                _record_failure(
                    student_root, stu, url,
                    status="commit_lookup_failed",
                    reason="GitHub commits API error",
                    detail=str(e),
                )
                continue
            if not commit_sha:
                student_root = os.path.join(suite_dir, stu)
                _record_failure(
                    student_root, stu, url,
                    status="no_commit_before_limit",
                    reason=f"No commit on '{branch}' <= {limit_dt.isoformat()}",
                )
                continue
            print(f"[{stu}] Using commit {commit_sha} (<= {limit_dt.isoformat()})")
        else:
            try:
                commit_sha = get_branch_head(owner, repo, branch, token)
                print(f"[{stu}] Using branch HEAD {commit_sha}")
            except Exception as e:
                _record_failure(
                    student_root, stu, url,
                    status="head_lookup_failed",
                    reason="Could not resolve branch HEAD",
                    detail=str(e),
                )
                continue

        # 1) Decide how to handle the representative path
        rep_meta = get_content_meta(owner, repo, path, commit_sha, token)
        rep_saved = False
        skip_paths = set()  # paths to skip in tree loop to avoid duplicates

        if rep_meta and rep_meta["type"] == "file":
            rep_rel = rep_meta["path"]              # repo-relative UTF-8 path
            rep_basename = os.path.basename(unquote(rep_rel))
            rep_is_c = rep_basename.lower().endswith(".c")

            # Case A) representative is a .c file
            if rep_is_c and not args.force_rename:
                # Do NOT create an extra main.c copy to avoid duplicate mains.
                # We rely on tree collection to fetch this .c file (and others).
                print(f"[{stu}] representative is .c; not duplicating as {args.rename_to}.")
                rep_saved = False
                # nothing added to skip_paths here; we want tree to stage it normally.

                _write_main_hint(student_root, rep_rel)

            else:
                # Case B) representative is not .c (or force-rename enabled)
                # Fetch and save to student root as rename_to (e.g., main.c)
                rep_enc = _encode_path_preserving_segments(unquote(rep_rel))
                rep_raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_sha}/{rep_enc}"
                try:
                    data = fetch_raw(rep_raw, token)

                    # always save as rename_to for compilation readiness
                    target_main = os.path.join(suite_dir, stu, args.rename_to)
                    safe_write(target_main, data)

                    _write_main_hint(student_root, args.rename_to)

                    _write_submission_meta(student_root, {
                        "submitted_url": url,
                        "submitted_kind": "non_c_file",  # non_c_file | dir | repo
                        "submitted_path": rep_rel,
                        "saved_as": args.rename_to
                    })

                    # optionally keep original name at root ONLY when it won't collide
                    # Note: to avoid multi-main, we do NOT write an extra .c at root if rep_is_c
                    if args.keep_original and not rep_is_c:
                        target_orig = os.path.join(suite_dir, stu, rep_basename)
                        if not os.path.exists(target_orig):
                            safe_write(target_orig, data)

                    print(f"[{stu}] representative saved as {args.rename_to}"
                        f"{' (orig kept)' if (args.keep_original and not rep_is_c) else ''}")
                    rep_saved = True

                    # If we forced a duplicate of a .c (force-rename), then skip original path in tree
                    if rep_is_c and args.force_rename:
                        skip_paths.add(rep_rel)

                except Exception as e:
                    print(f"[{stu}] representative fetch failed: {e}", file=sys.stderr)
                    _record_failure(
                        student_root, stu, url,
                        status="representative_fetch_failed",
                        reason=f"Failed to fetch representative path '{rep_rel}'",
                        detail=str(e),
                    )
                    rep_saved = False

        # If representative URL points to a directory, force the scope to that directory
        dir_scope_prefix: Optional[str] = None
        if rep_meta and rep_meta["type"] == "dir":
            # directory URL like /tree/<branch>/<path>
            dir_scope_prefix = unquote(path).strip("/")  # may be ""
        elif rep_meta is None and path == "":
            # repository root URL → treat as directory scope at repo root
            dir_scope_prefix = ""  # empty = repo root

        # 2) Then fetch .c/.h by scope (repo/dir)
        scope_prefix = None
        if dir_scope_prefix is not None:
            # Directory URL → force scope to that directory
            scope_prefix = dir_scope_prefix
        elif args.scope == "dir":
            # if rep path is a file, use its directory; if dir, use itself
            if rep_meta and rep_meta["type"] == "file":
                scope_prefix = os.path.dirname(unquote(rep_meta["path"]))
            else:
                scope_prefix = os.path.dirname(unquote(path)) if os.path.splitext(unquote(path))[1] else unquote(path)

        try:
            paths = list_tree_c_h_paths(owner, repo, commit_sha, token, scope_prefix)
        except Exception as e:
            print(f"[{stu}] tree list failed: {e}", file=sys.stderr)
            _record_failure(
                student_root, stu, url,
                status="tree_list_failed",
                reason="Failed to enumerate repository tree",
                detail=str(e),
            )
            paths = []

        staged_count = 0
        for p in paths:
            # Deduplicate: skip representative path if we already created a main.c copy for it
            if p in skip_paths:
                continue

            p_enc = _encode_path_preserving_segments(p)
            raw_p = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_sha}/{p_enc}"
            try:
                data = fetch_raw(raw_p, token)
            except Exception as e:
                print(f"[{stu}] fetch failed for {p}: {e}", file=sys.stderr)
                continue

            if args.preserve_subdirs:
                local_path = os.path.join(suite_dir, stu, p)
            else:
                local_path = os.path.join(suite_dir, stu, os.path.basename(unquote(p)))

            safe_write(local_path, data)
            staged_count += 1

        # After staging files, if this was a directory URL, auto-pick main and write hint
        if dir_scope_prefix is not None:
            picked = _pick_main_from_staged(
                student_root=student_root,
                scope_prefix=dir_scope_prefix,   # "" for repo root
                staged_paths=paths,
                preserve_subdirs=args.preserve_subdirs
            )
            if picked:
                _write_main_hint(student_root, picked)
                _write_submission_meta(student_root, {
                    "submitted_url": url,
                    "submitted_kind": "dir" if rep_meta and rep_meta["type"] == "dir" else "repo",
                    "auto_picked_main": picked
                })

                print(f"[{stu}] directory-scope main selected: {picked}")
            else:
                _record_failure(
                    student_root, stu, url,
                    status="auto_pick_main_failed",
                    reason="Could not determine a unique main() under directory scope",
                )
                print(f"[{stu}] directory-scope main not determined (no unique main).")

        if not rep_saved and not paths:
            _record_failure(
                student_root, stu, url,
                status="no_sources_found",
                reason=f"No representative file or .c/.h found at commit {commit_sha}",
            )
            print(f"[{stu}] No representative file or .c/.h found at commit {commit_sha}; skipping student.")
            continue

        print(f"[{stu}] staged {staged_count} additional .c/.h under {os.path.join(suite_dir, stu)}")
        staged_students += 1

    print(f"Staged students: {staged_students}, Suite: {args.suite}, Root: {suite_dir}")

if __name__ == "__main__":
    main()
