"""Dataverse Web API の薄いクライアント（az CLI のトークンを使う）。

トークン: `az account get-access-token --resource <ORG_URL>`。拒否された場合は
azure-identity の InteractiveBrowserCredential に退避する。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any

import httpx

import settings

SOLUTION = None  # このプロジェクトはソリューションを作っていない


def get_token() -> str:
    org_url = settings.get("org_url")
    try:
        out = subprocess.run(
            ["az", "account", "get-access-token", "--resource", org_url, "--query", "accessToken", "-o", "tsv"],
            check=True, capture_output=True, text=True, timeout=60,
        )
        token = out.stdout.strip()
        if token:
            return token
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"[warn] az token failed: {getattr(exc, 'stderr', exc)}", file=sys.stderr)
    from azure.identity import InteractiveBrowserCredential  # 退避

    cred = InteractiveBrowserCredential(tenant_id=settings.get("tenant_id"))
    return cred.get_token(f"{org_url}/.default").token


class Dataverse:
    def __init__(self, token: str | None = None, solution: str | None = SOLUTION):
        self.token = token or get_token()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        }
        if solution:
            headers["MSCRM.SolutionUniqueName"] = solution
        self.http = httpx.Client(base_url=f"{settings.get('org_url')}/api/data/v9.2", headers=headers, timeout=120)

    def request(self, method: str, path: str, body: Any | None = None, headers: dict | None = None,
                ok: tuple[int, ...] = (200, 201, 204)) -> httpx.Response:
        for attempt in range(4):
            r = self.http.request(method, path, content=json.dumps(body) if body is not None else None, headers=headers)
            if r.status_code == 401 and attempt == 0:
                # トークン期限切れ → 取り直して 1 回だけ再試行
                self.token = get_token()
                self.http.headers["Authorization"] = f"Bearer {self.token}"
                continue
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("Retry-After", 2 * (attempt + 1)))
                time.sleep(wait)
                continue
            break
        if r.status_code not in ok:
            raise RuntimeError(f"{method} {path} -> {r.status_code}\n{r.text[:2000]}")
        return r

    def get(self, path: str, ok=(200,)) -> dict:
        return self.request("GET", path, ok=ok).json()

    def exists(self, path: str) -> bool:
        r = self.request("GET", path, ok=(200, 404))
        return r.status_code == 200

    def whoami(self) -> dict:
        return self.get("WhoAmI")

    def language_code(self) -> int:
        data = self.get("organizations?$select=languagecode")
        return int(data["value"][0]["languagecode"])

    def upsert(self, entity_set: str, key: str, body: dict) -> httpx.Response:
        """代替キー upsert。key は `gr_docid='x'` 形式。"""
        return self.request("PATCH", f"{entity_set}({key})", body, ok=(200, 204))
