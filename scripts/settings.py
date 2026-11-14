"""環境ごとの値（URL・ID）を config.local.json から読む。このファイルは Git に入れない。

config.example.json を config.local.json にコピーし、自分の環境の値を入れて使う。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "config.local.json"


def get(key: str) -> str:
    if not LOCAL.exists():
        raise SystemExit("config.local.json がありません。config.example.json をコピーして、自分の環境の値を入れてください。")
    value = json.loads(LOCAL.read_text(encoding="utf-8")).get(key, "")
    if not value or value.startswith("<"):
        raise SystemExit(f"config.local.json の {key} が未設定です。")
    return value
