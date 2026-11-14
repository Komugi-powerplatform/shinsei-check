"""公開するファイルに、環境固有の ID・個人名・手元のパスが残っていないこと。"""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
PATTERNS = {
    "GUID": GUID,
    "Dataverse の URL": re.compile(r"org[0-9a-f]{6,}\.crm\d*\.dynamics\.com", re.I),
    "テナントのドメイン": re.compile(r"[\w.-]+\.onmicrosoft\.com", re.I),
    "メールアドレス": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "手元のパス": re.compile(r"/Users/\w+|~/\.claude"),
    "署名つき URL": re.compile(r"[?&]sig=[\w%-]+"),
}
TEXT = {".py", ".md", ".json", ".toml", ".txt", ".log", ".yml", ".yaml", ".cfg", ""}


def published_files() -> list[Path]:
    """Git が追跡するファイルと、ignore されていない未追跡ファイル。"""
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, check=True, timeout=30).stdout
    return [ROOT / line for line in out.splitlines() if line and (ROOT / line).is_file()]


def test_local_config_is_ignored():
    names = {p.relative_to(ROOT).as_posix() for p in published_files()}
    assert "config.local.json" not in names
    assert "config.example.json" in names


def test_no_environment_ids_or_personal_data_in_published_files():
    hits = []
    for path in published_files():
        if path.suffix not in TEXT or path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pat in PATTERNS.items():
            for m in pat.finditer(text):
                hits.append(f"{path.relative_to(ROOT)}: {label}: {m.group(0)[:60]}")
    assert not hits, "\n".join(hits[:40])


def test_local_config_values_do_not_appear_anywhere():
    local = ROOT / "config.local.json"
    if not local.exists():
        return
    config = json.loads(local.read_text(encoding="utf-8"))
    values = [v for v in config.values() if isinstance(v, str) and len(v) >= 6]
    # private_words: 公開したくない語（氏名など）。大文字と小文字は区別しない
    words = [w.lower() for w in config.get("private_words", [])]
    hits = []
    for path in published_files():
        data = path.read_bytes()
        hits += [f"{path.relative_to(ROOT)}: {v[:12]}…" for v in values if v.encode() in data]
        low = data.lower()
        if path.name != "LICENSE":  # 著作権者の表示は公開している名義なので除く
            hits += [f"{path.relative_to(ROOT)}: private_words の語" for w in words if w.encode() in low]
    assert not hits, "\n".join(hits[:40])


def test_example_config_has_only_placeholders():
    example = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    assert all(isinstance(v, str) and v.startswith("<") and v.endswith(">") for k, v in example.items() if k != "private_words")
    assert example.get("private_words") == []
