# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import logging

from grade_fetcher.github_client import GitHubClient
from grade_fetcher.models import Config
from grade_fetcher.service import FetchService


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Fetch C/H sources and the representative file from GitHub per student.")
    ap.add_argument("--map", required=True, help="Path to student map JSON (list or {limit, students}).")
    ap.add_argument("--suite", required=True, help="Suite name (staged under data/<suite>/).")
    ap.add_argument("--data-root", default="data", help="Root data directory (default: data).")
    ap.add_argument("--rename-to", default="main.c", help="Also save representative file as this name at student root (default: main.c).")
    ap.add_argument("--keep-original", action="store_true", help="Also save representative file with its original filename at student root.")
    ap.add_argument("--respect-limit", action="store_true", help="Respect 'limit' field in map JSON (ISO 8601).")
    ap.add_argument("--scope", choices=["repo", "dir"], default="repo", help="Fetch scope: whole repo or only under representative directory.")
    ap.add_argument("--preserve-subdirs", action="store_true", default=True, help="Preserve original subdirectory structure when staging .c/.h.")
    ap.add_argument("--force-rename", action="store_true", help="Force saving representative file as rename-to even if it is a .c file.")
    ap.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"])  # default quiet
    return ap


def main() -> None:
    ap = build_argparser()
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s [%(levelname)s] %(message)s")

    cfg = Config(
        map_path=args.map,
        suite=args.suite,
        data_root=args.data_root,
        rename_to=args.rename_to,
        keep_original=args.keep_original,
        respect_limit=args.respect_limit,
        scope=args.scope,
        preserve_subdirs=args.preserve_subdirs,
        force_rename=args.force_rename,
        github_token=(os.environ.get("GITHUB_TOKEN") or "").strip() or None,
    )

    gh = GitHubClient(cfg.github_token)
    svc = FetchService(cfg, gh)

    with open(cfg.map_path, "r", encoding="utf-8") as f:
        map_data = json.load(f)

    svc.run_for_map(map_data)


if __name__ == "__main__":
    main()