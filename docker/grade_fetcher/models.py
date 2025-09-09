# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class Status(Enum):
    # Keep keys identical to the legacy script for meta compatibility
    URL_PARSE_FAILED = "url_parse_failed"
    DEFAULT_BRANCH_FAILED = "default_branch_failed"
    COMMIT_LOOKUP_FAILED = "commit_lookup_failed"
    NO_COMMIT_BEFORE_LIMIT = "no_commit_before_limit"
    HEAD_LOOKUP_FAILED = "head_lookup_failed"
    REPRESENTATIVE_FETCH_FAILED = "representative_fetch_failed"
    TREE_LIST_FAILED = "tree_list_failed"
    AUTO_PICK_MAIN_FAILED = "auto_pick_main_failed"
    NO_SOURCES_FOUND = "no_sources_found"


@dataclass
class Config:
    map_path: str
    suite: str
    data_root: str = "data"
    rename_to: str = "main.c"
    keep_original: bool = False
    respect_limit: bool = False
    scope: str = "repo" # "repo" | "dir"
    preserve_subdirs: bool = True
    force_rename: bool = False
    github_token: Optional[str] = None

    def suite_dir(self) -> str:
        return os.path.join(self.data_root, self.suite)


@dataclass
class RepoRef:
    owner: str
    repo: str
    branch: Optional[str]
    path: str # may be ""