# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

# Keep pattern identical to legacy behavior
MAIN_PATTERN = re.compile(r"\bint\s+main\s*\(")


@dataclass
class Config:
    """CLI/runtime configuration mapped 1:1 from legacy script."""

    suite_name: str = "suite"

    # Single-file mode
    src: Optional[str] = None

    # Multi-file mode
    src_dir: Optional[str] = None
    recursive: bool = True
    allow_make: bool = False

    # Build & run
    tests_path: Optional[str] = None
    bin_out: str = os.environ.get("BIN_OUT", "/work/a.out")
    cflags: str = os.environ.get("CFLAGS", "-O2 -std=c17 -Wall -Wextra")
    timeout: float = 2.0
    strip_mode: str = "right"  # none|left|right|both
    normalize_newlines: bool = False
    case_sensitive: bool = False
    main_filename: str = "main.c"

    # Reporting
    report_path: Optional[str] = None
    summarize_dir: Optional[str] = None

    # Derived convenience values
    @property
    def has_single_file(self) -> bool:
        return bool(self.src) and not self.src_dir

    @property
    def has_multi_file(self) -> bool:
        return bool(self.src_dir)