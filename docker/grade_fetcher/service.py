# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from .github_client import GitHubClient
from .models import Config, RepoRef, Status
from .staging import (
    ensure_dir,
    filter_c_h_paths,
    pick_main_from_staged,
    record_failure,
    safe_write,
    write_json_merge,
    write_main_hint,
)
from .url_parser import parse_repo_url


class FetchService:
    """Application orchestration that wires GitHubClient + staging.

    This service preserves console outputs and meta file schema of the legacy script.
    """

    def __init__(self, cfg: Config, gh: GitHubClient):
        self.cfg = cfg
        self.gh = gh

    # ----- internals -----

    def _resolve_ref(self, stu_id:str, r: RepoRef, limit_dt: Optional[datetime]) -> Optional[str]:
        """Resolve commit SHA based on branch + optional time limit."""
        branch = r.branch
        if branch is None:
            try:
                branch = self.gh.get_default_branch(r.owner, r.repo)
                print(f"[{stu_id}] Using default branch '{branch}' (repo root URL)")
            except Exception as e:
                raise RuntimeError(f"Could not resolve default branch: {e}")

        if limit_dt is not None:
            sha = self.gh.get_commit_before(r.owner, r.repo, branch, limit_dt)
            return sha
        return self.gh.get_branch_head(r.owner, r.repo, branch)

    def _stage_student(self, stu_id: str, submitted_url: str, r: RepoRef, sha: str) -> bool:
        student_root = os.path.join(self.cfg.suite_dir(), stu_id)
        ensure_dir(student_root)

        # Representative meta (file/dir)
        rep_meta = self.gh.get_contents_meta(r.owner, r.repo, r.path, sha)
        rep_saved = False
        skip_paths: set[str] = set()

        # Representative is a file → possibly save as rename_to
        if rep_meta and rep_meta["type"] == "file":
            rep_rel = rep_meta["path"]
            rep_base = os.path.basename(rep_rel)
            rep_is_c = rep_base.lower().endswith(".c")

            if rep_is_c and not self.cfg.force_rename:
                # Legacy behavior: do not duplicate main.c at root; rely on tree staging
                print(f"[{stu_id}] representative is .c; not duplicating as {self.cfg.rename_to}.")
                write_main_hint(student_root, rep_rel)
            else:
                try:
                    data = self.gh.fetch_raw(r.owner, r.repo, sha, rep_rel)
                    # Always save as rename_to to make compilation ready
                    target_main = os.path.join(student_root, self.cfg.rename_to)
                    safe_write(target_main, data)
                    write_main_hint(student_root, self.cfg.rename_to)
                    write_json_merge(os.path.join(student_root, ".submission_meta.json"), {
                        "submitted_url": submitted_url,
                        "submitted_kind": "non_c_file",
                        "submitted_path": rep_rel,
                        "saved_as": self.cfg.rename_to,
                    })
                    if self.cfg.keep_original and not rep_is_c:
                        target_orig = os.path.join(student_root, rep_base)
                        if not os.path.exists(target_orig):
                            safe_write(target_orig, data)
                    print(f"[{stu_id}] representative saved as {self.cfg.rename_to}{' (orig kept)' if (self.cfg.keep_original and not rep_is_c) else ''}")
                    rep_saved = True
                    if rep_is_c and self.cfg.force_rename:
                        skip_paths.add(rep_rel)
                except Exception as e:
                    record_failure(student_root, submitted_url, Status.REPRESENTATIVE_FETCH_FAILED,
                                   f"Failed to fetch representative path '{rep_rel}'", str(e))
                    rep_saved = False

        # Directory scope decision
        dir_scope_prefix: Optional[str] = None
        if rep_meta and rep_meta.get("type") == "dir":
            dir_scope_prefix = (r.path or "").strip("/")
        elif rep_meta is None and r.path == "":
            dir_scope_prefix = ""  # repo root

        # List C/H paths in scope and stage
        try:
            tree = self.gh.list_tree(r.owner, r.repo, sha)
            if dir_scope_prefix is not None:
                scope_prefix = dir_scope_prefix
            elif self.cfg.scope == "dir":
                scope_prefix = os.path.dirname(r.path) if r.path else ""
            else:
                scope_prefix = None
            paths = filter_c_h_paths(tree, scope_prefix)
        except Exception as e:
            record_failure(student_root, submitted_url, Status.TREE_LIST_FAILED, "Failed to enumerate repository tree", str(e))
            paths = []

        staged_count = 0
        for p in paths:
            if p in skip_paths:
                continue
            try:
                data = self.gh.fetch_raw(r.owner, r.repo, sha, p)
            except Exception as e:
                # Non-fatal per-file fetch failure
                print(f"[{stu_id}] fetch failed for {p}: {e}")
                continue

            if self.cfg.preserve_subdirs:
                dst = os.path.join(student_root, p)
            else:
                dst = os.path.join(student_root, os.path.basename(p))
            safe_write(dst, data)
            staged_count += 1

        if dir_scope_prefix is not None:
            picked = pick_main_from_staged(student_root, dir_scope_prefix, paths)
            if picked:
                write_main_hint(student_root, picked)
                write_json_merge(os.path.join(student_root, ".submission_meta.json"), {
                    "submitted_url": submitted_url,
                    "submitted_kind": "dir" if rep_meta and rep_meta.get("type") == "dir" else "repo",
                    "auto_picked_main": picked,
                })
                print(f"[{stu_id}] directory-scope main selected: {picked}")
            else:
                record_failure(student_root, submitted_url, Status.AUTO_PICK_MAIN_FAILED,
                               "Could not determine a unique main() under directory scope")
                print(f"[{stu_id}] directory-scope main not determined (no unique main).")

        if not rep_saved and not paths:
            record_failure(student_root, submitted_url, Status.NO_SOURCES_FOUND,
                           f"No representative file or .c/.h found at commit {sha}")
            print(f"[{stu_id}] No representative file or .c/.h found at commit {sha}; skipping student.")
            return False

        print(f"[{stu_id}] staged {staged_count} additional .c/.h under {os.path.join(self.cfg.suite_dir(), stu_id)}")
        return True

    # ----- public -----

    def run_for_map(self, map_data: dict | list) -> None:
        # Resolve limit and students list (kept compatible)
        limit_dt: Optional[datetime] = None
        if self.cfg.respect_limit and isinstance(map_data, dict) and "limit" in map_data:
            limit_dt = datetime.fromisoformat(map_data["limit"].replace("Z", "+00:00")).astimezone(timezone.utc)
            students = map_data.get("students", [])
        elif isinstance(map_data, list):
            students = map_data
        elif isinstance(map_data, dict) and "students" in map_data:
            students = map_data["students"]
        else:
            raise ValueError("Invalid map JSON format")

        ensure_dir(self.cfg.suite_dir())

        staged_students = 0
        for it in students:
            stu = it.get("id")
            url = it.get("url")
            if not stu or not url:
                continue

            student_root = os.path.join(self.cfg.suite_dir(), stu)

            # Parse URL → RepoRef
            try:
                ref = parse_repo_url(url)
                print(f"[{stu}] Parsed repo URL: {ref}")
            except Exception as e:
                record_failure(student_root, url, Status.URL_PARSE_FAILED, "Unrecognized or unsupported GitHub URL", str(e))
                continue

            # Resolve commit SHA
            try:
                sha = self._resolve_ref(stu, ref, limit_dt)
            except Exception as e:
                # Map to legacy-like statuses
                if ref.branch is None:
                    record_failure(student_root, url, Status.DEFAULT_BRANCH_FAILED, "Could not resolve default branch", str(e))
                else:
                    record_failure(student_root, url, Status.HEAD_LOOKUP_FAILED, "Could not resolve branch HEAD", str(e))
                continue

            if limit_dt is not None and not sha:
                record_failure(student_root, url, Status.NO_COMMIT_BEFORE_LIMIT, f"No commit on '{ref.branch}' <= {limit_dt.isoformat()}")
                continue

            # Info prints kept similar to legacy
            if limit_dt is not None:
                print(f"[{stu}] Using commit {sha} (<= {limit_dt.isoformat()})")
            else:
                print(f"[{stu}] Using branch HEAD {sha}")

            ok = self._stage_student(stu, url, ref, sha)
            if ok:
                staged_students += 1

        print(f"Staged students: {staged_students}, Suite: {self.cfg.suite}, Root: {self.cfg.suite_dir()}")
