"""v2 サンプル 20 件の受入条件。仕込んだ不備と判定エンジン（規程 v2）の結果が一致すること。"""

import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from shinsei.rules import check, load_rules

ROOT = Path(__file__).resolve().parents[1]
V2 = load_rules("rules.v2.json")
SRC = json.loads((ROOT / "samples" / "v2" / "cases.src.json").read_text(encoding="utf-8"))
GEN = json.loads((ROOT / "samples" / "v2" / "cases.json").read_text(encoding="utf-8"))
FILES = ROOT / "samples" / "v2" / "files"


def test_ids():
    assert [c["id"] for c in SRC] == [f"V{i:02d}" for i in range(1, 21)]


@pytest.mark.parametrize("case", SRC, ids=lambda c: c["id"])
def test_intended_defects_match_engine(case):
    assert [f["rule"] for f in check(case["app"], V2)] == case["intended"]


def test_distribution():
    n = Counter(min(len(c["intended"]), 2) for c in SRC)  # 0・1・2 以上
    assert (n[0], n[1], n[2]) == (4, 8, 8)
    assert Counter(c["format"] for c in SRC) == {"hw-scan": 8, "pdf2": 6, "scan2": 4, "hw-photo": 2}


def test_rule_coverage():
    cases_with = Counter(r for c in SRC for r in set(c["intended"]))
    assert set(cases_with) == {"R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"}
    assert min(cases_with.values()) >= 2
    assert cases_with["R7"] >= 3 and cases_with["R8"] >= 3
    # 規程 v2 で足した条件に触れる申請書が 3 件以上あること
    lodging = [c for c in SRC if c["app"]["type"] == "shucchou" and (c["app"]["applicant_class"] == "管理職" or "市" in c["app"]["destination"])]
    external = [c for c in SRC if c["app"].get("external_participants")]
    assert len(lodging) >= 3 and len(external) >= 3


def test_long_cases_span_two_pages():
    for c in GEN:
        if c["format"] in ("pdf2", "scan2"):
            assert len(c["app"]["items"]) >= 15, c["id"]
            info = subprocess.run(["pdfinfo", str(FILES / c["file"])], capture_output=True, text=True, timeout=30).stdout
            assert "Pages:           2" in info, c["id"]


def test_generated_matches_source_and_files_exist():
    assert len(list(FILES.iterdir())) == 20
    for src, gen in zip(SRC, GEN):
        assert gen["app"] == src["app"] and gen["expected"] == check(src["app"], V2)
        path = FILES / gen["file"]
        assert path.suffix == (".jpg" if gen["format"] == "hw-photo" else ".pdf")
        assert path.stat().st_size > 10_000


def test_only_pdf2_has_text_layer():
    def text(name):
        return subprocess.run(["pdftotext", str(FILES / name), "-"], capture_output=True, text=True, timeout=30).stdout

    assert "タクシー" in text("V02_keihi.pdf")
    assert text("V01_keihi.pdf").strip() == "" and text("V04_ringi.pdf").strip() == ""


def test_kitei_v2_pdfs_exist():
    assert len(list((ROOT / "kitei" / "v2" / "pdf").glob("*.pdf"))) == 3
