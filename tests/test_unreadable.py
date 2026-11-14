"""判定に必須の値を読めなかったときは、0 や空として判定を続けず「判定できない」とする。"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from shinsei.rules import missing_required

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ringi():
    return {
        "type": "ringi", "apply_date": "2026-11-10", "amount": 298000,
        "items": [{"name": "ノート PC 2 台", "category": "備品", "amount": 298000}],
        "purpose": "端末の購入", "approver_position": "部長", "attachments": ["見積書"],
    }


def test_complete_app_has_nothing_missing(ringi):
    assert missing_required(ringi) == []


def test_null_amount_is_missing_not_zero(ringi):
    """V17 の再現: 抽出が申請金額を null で返した。"""
    ringi["amount"] = None
    assert missing_required(ringi) == ["申請金額"]


def test_zero_amount_is_a_value(ringi):
    ringi["amount"] = 0
    assert missing_required(ringi) == []


@pytest.mark.parametrize("items", [None, []])
def test_empty_items_is_missing(ringi, items):
    ringi["items"] = items
    assert missing_required(ringi) == ["明細"]


@pytest.mark.parametrize("value", [None, "", "  "])
def test_blank_apply_date_is_missing(ringi, value):
    ringi["apply_date"] = value
    assert missing_required(ringi) == ["申請日"]


@pytest.mark.parametrize("value", [None, "", "seikyu"])
def test_unknown_type_is_missing(ringi, value):
    ringi["type"] = value
    assert missing_required(ringi) == ["申請種別"]


def test_type_specific_dates(ringi):
    assert missing_required(ringi | {"type": "keihi"}) == ["支払日"]
    assert missing_required(ringi | {"type": "shucchou"}) == ["出発日"]
    assert missing_required(ringi | {"type": "keihi", "pay_date": "2026-11-05"}) == []


def test_blank_purpose_and_approver_are_defects_not_unreadable(ringi):
    """目的・決裁者の空欄は申請書の不備（R5・R2）として指摘する。読み取り失敗とは扱わない。"""
    assert missing_required(ringi | {"purpose": "", "approver_position": ""}) == []


def test_several_missing_keep_order(ringi):
    assert missing_required(ringi | {"amount": None, "items": [], "apply_date": None}) == ["申請金額", "明細", "申請日"]


# --- フロー定義: 3 本とも、読めなかった項目があれば unreadable を返し、指摘を出さない ---


@pytest.fixture(scope="module")
def flows():
    for script in ("build.py", "build_v2.py"):
        subprocess.run([sys.executable, str(ROOT / "flows" / script), "--dry-run"], check=True, capture_output=True, timeout=120)
    names = ("Shinsei_Check", "Shinsei_Check_HTTP", "Shinsei_Check_v2_HTTP")
    return {n: json.loads((ROOT / "flows" / "out" / f"{n}.clientdata.json").read_text(encoding="utf-8"))["properties"]["definition"]["actions"]
            for n in names}


@pytest.mark.parametrize("name", ["Shinsei_Check", "Shinsei_Check_HTTP", "Shinsei_Check_v2_HTTP"])
def test_flow_returns_unreadable_when_required_value_is_missing(flows, name):
    acts = flows[name]
    candidates = acts["Compose_missing_candidates"]["inputs"]
    for label in ("申請金額", "明細", "申請日", "支払日", "出発日"):
        assert label in candidates, label
    assert "equals(outputs('Compose_app')?['amount'], null)" in candidates
    result = acts["Compose_result"]["inputs"]
    assert "body('Filter_missing')" in result["status"]
    assert "body('Filter_missing')" in result["findings"]
    assert result["missing"] == "@body('Filter_missing')"
    # 金額を使う計算より前に、読めたかどうかを確かめている
    order = list(acts)
    assert order.index("Filter_missing") < order.index("V_need")
