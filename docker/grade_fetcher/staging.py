# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
from typing import Iterable, List, Optional

from .models import Status
from .url_parser import MAIN_RE


# -------- Filesystem helpers --------

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def safe_write(path: str, data: bytes) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "wb") as f:
        f.write(data)


def write_json_merge(path: str, patch: dict) -> None:
    """Merge/append JSON (best effort)."""
    ensure_dir(os.path.dirname(path))
    try:
        current = {}
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                current = json.load(f)
        current.update(patch)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    except Exception:
        # Do not break pipeline on meta write failure
        logging.exception("meta write failed (non-fatal)")


def record_failure(student_root: str, submitted_url: str, status: Status, reason: str, detail: Optional[str] = None) -> None:
    payload = {
        "submitted_url": submitted_url,
        "status": status.value,
        "failure_reason": reason,
    }
    if detail:
        payload["detail"] = str(detail)[:500]
    write_json_merge(os.path.join(student_root, ".submission_meta.json"), payload)
    print(f"[{os.path.basename(student_root)}] ERROR {status.value}: {reason}")  # Preserve legacy console style


# -------- Pure logic --------

def has_main_function(text: str) -> bool:
    return bool(MAIN_RE.search(text))


def filter_c_h_paths(tree: Iterable[dict], scope_prefix: Optional[str]) -> List[str]:
    """Select .c/.h under optional scope prefix. Pure function."""
    out: List[str] = []
    for ent in tree:
        if ent.get("type") != "blob":
            continue
        p = ent.get("path", "")
        if scope_prefix and not (p == scope_prefix or p.startswith(scope_prefix.rstrip("/") + "/")):
            continue
        if p.lower().endswith((".c", ".h")):
            out.append(p)
    return out


def write_main_hint(student_root: str, rel_path: str) -> None:
    ensure_dir(student_root)
    with open(os.path.join(student_root, ".main_filename"), "w", encoding="utf-8") as f:
        f.write(rel_path.strip() + "\n")


def pick_main_from_staged(student_root: str, scope_prefix: str, staged_paths: List[str]) -> Optional[str]:
    """Prefer '<scope>/main.c', else the unique .c that contains main()."""
    scope_prefix = (scope_prefix or "").strip("/")
    c_paths = [p for p in staged_paths if p.lower().endswith(".c") and (scope_prefix == "" or p == scope_prefix or p.startswith(scope_prefix + "/"))]

    # 1) Prefer explicit main.c at the scope
    candidate_rel = f"{scope_prefix}/main.c" if scope_prefix else "main.c"
    local_main = os.path.join(student_root, candidate_rel)
    if os.path.isfile(local_main):
        return candidate_rel

    # 2) Unique file that contains main()
    candidates: List[str] = []
    for rel in c_paths:
        local = os.path.join(student_root, rel)
        try:
            with open(local, "r", encoding="utf-8", errors="ignore") as f:
                if has_main_function(f.read()):
                    candidates.append(rel)
        except Exception:
            continue
    if len(candidates) == 1:
        return candidates[0]
    return None