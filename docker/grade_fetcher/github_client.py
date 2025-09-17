# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import requests

from .url_parser import encode_path_preserving_segments


class GitHubClient:
    """Thin wrapper around GitHub API with retry/backoff and raw fetch."""

    def __init__(self, token: Optional[str]):
        self.s = requests.Session()
        self.token = token

    def _headers(self, accept: str = "application/vnd.github+json") -> dict:
        h = {"Accept": accept}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, url: str, *, params: Optional[dict] = None, raw: bool = False, max_tries: int = 6) -> requests.Response:
        """HTTP GET with simple exponential backoff for 403/429."""
        backoff = 1.0
        for attempt in range(1, max_tries + 1):
            resp = self.s.get(
                url,
                headers=self._headers("application/vnd.github.v3.raw" if raw else "application/vnd.github+json"),
                params=params,
                timeout=30,
            )
            if resp.status_code == 200:
                return resp
            if resp.status_code in (403, 429):
                reset = resp.headers.get("X-RateLimit-Reset")
                if reset and reset.isdigit():
                    sleep_s = max(0, int(reset) - int(time.time()) + 1)
                else:
                    sleep_s = backoff
                logging.warning("Rate limited (%s). Sleeping %.1fs (try %d/%d)", resp.status_code, sleep_s, attempt, max_tries)
                time.sleep(sleep_s)
                backoff = min(backoff * 2, 60)
                continue
            # Non-retriable error
            raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:200]}")
        raise RuntimeError("GitHub API: exhausted retries")

    # --- High level endpoints ---

    def get_default_branch(self, owner: str, repo: str) -> str:
        data = self._get(f"https://api.github.com/repos/{owner}/{repo}").json()
        if "default_branch" not in data:
            raise RuntimeError("default_branch not found")
        return data["default_branch"]

    def get_branch_head(self, owner: str, repo: str, branch: str) -> str:
        data = self._get(f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}").json()
        return data["sha"]

    def get_commit_before(self, owner: str, repo: str, branch: str, limit_dt: datetime) -> Optional[str]:
        url = f"https://api.github.com/repos/{owner}/{repo}/commits"
        params = {"sha": branch, "per_page": 100}
        while True:
            resp = self._get(url, params=params)
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

    def list_tree(self, owner: str, repo: str, commit_sha: str) -> List[dict]:
        return self._get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{commit_sha}",
            params={"recursive": "1"},
        ).json().get("tree", [])

    def get_contents_meta(self, owner: str, repo: str, path: str, ref: str) -> Optional[dict]:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encode_path_preserving_segments(path)}"
        try:
            data = self._get(url, params={"ref": ref}).json()
        except Exception:
            return None
        if isinstance(data, dict) and data.get("type") == "file":
            return {"type": "file", "path": data.get("path"), "name": data.get("name")}
        if isinstance(data, list):
            return {"type": "dir", "path": path, "name": path.split("/")[-1]}
        return None

    def fetch_raw(self, owner: str, repo: str, ref: str, path: str) -> bytes:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{encode_path_preserving_segments(path)}"
        return self._get(url, raw=True).content
