# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import textwrap
from typing import List, Union


def read_tests(tests_path: str) -> List[dict]:
    with open(tests_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("tests.json must be a JSON array of test cases.")
    for i, t in enumerate(data):
        if "name" not in t:
            t["name"] = f"case-{i+1}"
        if "stdin" not in t:
            raise SystemExit(f"Test '{t['name']}' missing 'stdin'.")
        if "expected" not in t:
            raise SystemExit(f"Test '{t['name']}' missing 'expected'.")
    return data


def normalize(s: str, strip_mode: str, normalize_newlines: bool) -> str:
    if normalize_newlines:
        s = s.replace("\r\n", "\n").replace("\r", "\n")
    if strip_mode == "left":
        s = s.lstrip()
    elif strip_mode == "right":
        s = s.rstrip()
    elif strip_mode == "both":
        s = s.strip()
    elif strip_mode == "none":
        pass
    else:
        raise ValueError(f"Unknown strip mode: {strip_mode}")
    return s


def run_one(bin_path: str, stdin_data: str, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        [bin_path],
        input=stdin_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def diff_block(expected: str, got: str) -> str:
    exp_vis = expected.replace("\n", "\\n\n")
    got_vis = got.replace("\n", "\\n\n")
    return textwrap.dedent(
        f"""
        --- expected ---
        {exp_vis}
        ---   got    ---
        {got_vis}
        """
    ).rstrip()