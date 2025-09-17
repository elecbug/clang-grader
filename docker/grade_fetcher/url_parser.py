# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, unquote, quote
from typing import Optional

from .models import RepoRef

# --- Regex (kept compatible) ---
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

    Supported shapes: blob/raw/tree/repo root.
    """
    url = nfkc(url).strip()

    # Handle scp-like syntax
    if url.startswith("git@github.com:"):
        owner_repo = url[len("git@github.com:"):]
        if owner_repo.endswith(".git"):
            owner_repo = owner_repo[:-4]
        url = f"https://github.com/{owner_repo}"
    elif not urlsplit(url).scheme:
        # No scheme; try to recognize github host
        lower = url.lower()
        if lower.startswith("www.github.com/"):
            url = "https://" + url[4:]  # drop 'www.'
        elif lower.startswith("github.com/") or lower.startswith("raw.githubusercontent.com/"):
            url = "https://" + url

    parts = urlsplit(url)

    # Normalize scheme/netloc to lowercase
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if netloc == "www.github.com":
        netloc = "github.com"

    clean_url = urlunsplit((scheme, netloc, parts.path, "", ""))

    if clean_url.endswith(".git"):
        clean_url = clean_url[:-4]

    # --- Match blob ---
    m = BLOB_RE.match(clean_url)
    if m:
        return RepoRef(
            m["owner"],
            m["repo"],
            m["branch"],
            unquote(m["path"])  # decode %EA%... into real Unicode
        )

    # --- Match raw ---
    m = RAW_RE.match(clean_url)
    if m:
        return RepoRef(
            m["owner"],
            m["repo"],
            m["branch"],
            unquote(m["path"])
        )

    # --- Match tree ---
    m = TREE_RE.match(clean_url)
    if m:
        return RepoRef(
            m["owner"],
            m["repo"],
            m["branch"],
            unquote(m["path"] or "")
        )

    # --- Match repo root ---
    m = REPO_RE.match(clean_url)
    if m:
        return RepoRef(m["owner"], m["repo"], None, "")

    if "github.com" in clean_url or "raw.githubusercontent.com" in clean_url:
        raise ValueError(f"Unsupported GitHub URL shape: {url}")
    else:
        raise ValueError(f"Unrecognized GitHub URL: {url}")