"""サンプル 20 件の受入条件。手で書いた「仕込んだ不備」と判定エンジンの結果が一致すること。"""

import json
from collections import Counter
from pathlib import Path

import pytest

from shinsei.rules import check

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "samples" / "cases.src.json").read_text(encoding="utf-8"))


def test_twenty_cases_with_unique_ids():
    assert [c["id"] for c in CASES] == [f"{i:02d}" for i in range(1, 21)]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_intended_defects_match_engine(case):
    assert [f["rule"] for f in check(case["app"])] == case["intended"]


def test_defect_count_distribution():
    """不備なし 5 件・1 つ 10 件・2〜3 つ 5 件。"""
    n = Counter(len(c["intended"]) for c in CASES)
    assert n[0] == 5
    assert n[1] == 10
    assert n[2] + n[3] == 5
    assert set(n) <= {0, 1, 2, 3}


def test_every_rule_appears_at_least_twice():
    n = Counter(r for c in CASES for r in c["intended"])
    assert set(n) == {"R1", "R2", "R3", "R4", "R5", "R6"}
    assert min(n.values()) >= 2


def test_format_distribution():
    assert Counter(c["format"] for c in CASES) == {"pdf": 12, "scan": 6, "photo": 2}


def test_all_three_types_have_clean_and_defective_cases():
    for t in ("keihi", "shucchou", "ringi"):
        flags = {bool(c["intended"]) for c in CASES if c["app"]["type"] == t}
        assert flags == {True, False}, t


# --- 生成物（先に `python -m shinsei.generate` を実行しておく） ---

GENERATED = json.loads((ROOT / "samples" / "cases.json").read_text(encoding="utf-8"))


def test_generated_cases_match_source_and_engine():
    assert len(GENERATED) == 20
    for src, gen in zip(CASES, GENERATED):
        assert gen["app"] == src["app"]
        assert gen["expected"] == check(src["app"])
        assert all(f["article"] and f["reason"] for f in gen["expected"])


def test_generated_files_exist_with_expected_extension():
    ext = {"pdf": ".pdf", "scan": ".pdf", "photo": ".jpg"}
    for gen in GENERATED:
        path = ROOT / "samples" / "files" / gen["file"]
        assert path.suffix == ext[gen["format"]]
        assert path.stat().st_size > 10_000, path.name
    assert len(list((ROOT / "samples" / "files").iterdir())) == 20


def test_text_pdf_has_text_layer_and_scan_does_not():
    """文字つき PDF は文字を取り出せ、スキャン風は取り出せない（読み取り方式の差を見るため）。"""
    import subprocess

    def text(name):
        return subprocess.run(
            ["pdftotext", str(ROOT / "samples" / "files" / name), "-"], capture_output=True, text=True, timeout=30
        ).stdout

    assert "経費精算申請書" in text("01_keihi.pdf")
    assert text("03_shucchou.pdf").strip() == ""


def test_kitei_pdfs_exist():
    assert sorted(p.name for p in (ROOT / "kitei" / "pdf").glob("*.pdf")) == [
        "01-keihi.pdf",
        "02-shucchou.pdf",
        "03-kessai.pdf",
    ]
