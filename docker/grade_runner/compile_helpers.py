# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shlex
import subprocess
from typing import List, Optional, Tuple

from .models import MAIN_PATTERN


def read_submission_meta(src_dir: str) -> dict:
    """Read .submission_meta.json if present. Non-fatal on error."""
    path = os.path.join(src_dir, ".submission_meta.json")
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def is_main_file(path: str) -> bool:
    """Return True if the file contains a definition of int main(...)."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return bool(MAIN_PATTERN.search(f.read()))
    except Exception:
        # If unreadable, let the compiler handle; treat as non-main here.
        return False


def collect_sources_with_single_main(src_dir: str, main_filename: str, recursive: bool = True) -> List[str]:
    """Collect .c sources under src_dir such that only `main_filename` provides main().
    Any other .c that also defines main() will be skipped.
    """
    selected: List[str] = []
    main_path = os.path.join(src_dir, main_filename)
    if not os.path.isfile(main_path):
        return selected

    # Always include the representative main
    selected.append(os.path.abspath(main_path))

    # Walk and gather non-main .c files
    if recursive:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for fn in files:
                if not fn.endswith('.c'):
                    continue
                full = os.path.abspath(os.path.join(root, fn))
                if full == os.path.abspath(main_path):
                    continue
                if is_main_file(full):
                    print(f"[INFO] Skipping extra main in {full}")
                    continue
                selected.append(full)
    else:
        for fn in os.listdir(src_dir):
            if not fn.endswith('.c'):
                continue
            full = os.path.abspath(os.path.join(src_dir, fn))
            if full == os.path.abspath(main_path):
                continue
            if is_main_file(full):
                print(f"[INFO] Skipping extra main in {full}")
                continue
            selected.append(full)

    return selected


def find_c_files(src_dir: str, recursive: bool = True) -> List[str]:
    """Collect .c files under src_dir (recursive by default)."""
    c_files: List[str] = []
    if recursive:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for fn in files:
                if fn.endswith('.c'):
                    c_files.append(os.path.join(root, fn))
    else:
        for fn in os.listdir(src_dir):
            if fn.endswith('.c'):
                c_files.append(os.path.join(src_dir, fn))
    return c_files


def detect_multiple_mains(c_files: List[str]) -> Tuple[int, List[str]]:
    """Light-weight detection of multiple 'main' definitions to warn/fail early."""
    hits: List[str] = []
    for f in c_files:
        try:
            with open(f, 'r', encoding='utf-8', errors='ignore') as fh:
                if MAIN_PATTERN.search(fh.read()):
                    hits.append(f)
        except Exception:
            pass
    return (len(hits), hits)


def run_make(src_dir: str, env: Optional[dict] = None) -> Tuple[int, str, str]:
    """Run 'make' in the student directory if requested."""
    proc = subprocess.run(
        ["make", "-C", src_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def compile_c_single(src: str, bin_out: str, cflags: str) -> Optional[str]:
    """Compile single C source into an executable. Return stderr text on failure."""
    cmd = ["gcc"] + shlex.split(cflags) + ["-o", bin_out, src]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return (proc.stdout or "") + (proc.stderr or "")
    return None


def compile_c_multi(c_files: List[str], include_dirs: List[str], bin_out: str, cflags: str) -> Optional[str]:
    """Compile multiple C sources with include dirs into a single binary."""
    cmd = ["gcc"] + shlex.split(cflags)
    for inc in include_dirs:
        cmd.extend(["-I", inc])
    cmd.extend(c_files)
    cmd.extend(["-o", bin_out])
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return (proc.stdout or "") + (proc.stderr or "")
    return None