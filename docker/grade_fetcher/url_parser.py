# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, unquote, quote
from typing import Optional

from .models import RepoRef

# --- Regex (kept compatible) ---
BLOB_RE = re.compile( r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/blob/(?P<branch>[^/]+)/(?P<path>.+)$", re.IGNORECASE)
RAW_RE = re.compile( r"^https?://raw\.githubusercontent\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<branch>[^/]+)/(?P<path>.+)$", re.IGNORECASE)
TREE_RE = re.compile( r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/tree/(?P<branch>[^/]+)(?:/(?P<path>.*))?$", re.IGNORECASE)
REPO_RE = re.compile( r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/?$", re.IGNORECASE)

MAIN_RE = re.compile(r"\bint\s+main\s*\(")

def nfkc(s: str) -> str:
    """Normalize unicode to NFKC."""
    return unicodedata.normalize("NFKC", s)


def encode_path_preserving_segments(path: str) -> str:
    """Percent-encode each segment while preserving slashes.
    This matches the legacy behavior used to construct raw URLs.
    """
    segs = path.split("/")
    enc = [quote(unquote(seg), safe="") for seg in segs]
    return "/".join(enc)


def parse_repo_url(url: str) -> RepoRef:
    """Parse a GitHub URL into RepoRef. Raises ValueError on failure.

    Supported shapes are identical to the legacy script: blob/raw/tree/repo root.
    """
    url = nfkc(url).strip()
    parts = urlsplit(url)
    clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    if clean_url.endswith(".git"):
        clean_url = clean_url[:-4]

    m = BLOB_RE.match(clean_url)
    if m:
        return RepoRef(m["owner"], m["repo"], m["branch"], m["path"])

    m = RAW_RE.match(clean_url)
    if m:
        return RepoRef(m["owner"], m["repo"], m["branch"], m["path"])

    m = TREE_RE.match(clean_url)
    if m:
        return RepoRef(m["owner"], m["repo"], m["branch"], m["path"] or "")

    m = REPO_RE.match(clean_url)
    if m:
        return RepoRef(m["owner"], m["repo"], None, "")

    if "github.com" in clean_url:
        raise ValueError(f"Unsupported GitHub URL shape: {url}")
    raise ValueError(f"Unrecognized GitHub URL: {url}")
