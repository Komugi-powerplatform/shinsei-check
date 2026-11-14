"""判定エンジンの受入条件。申請書 1 件（抽出項目の dict）から指摘のリストを返す。"""

import copy

import pytest
from shinsei.rules import check


@pytest.fixture
def keihi():
    """不備のない経費精算（会議費・4 人・1 人 4,000 円）。"""
    return {
        "type": "keihi",
        "applicant": "佐藤 健二",
        "apply_date": "2026-11-10",
        "pay_date": "2026-11-05",
        "amount": 16000,
        "items": [{"name": "打合せ昼食", "category": "会議費", "amount": 16000}],
        "participants": 4,
        "purpose": "新製品の販促計画の打合せ",
        "approver_position": "課長",
        "attachments": ["領収書"],
    }


@pytest.fixture
def shucchou():
    """不備のない出張申請（2 泊・1 泊 11,000 円）。"""
    return {
        "type": "shucchou",
        "applicant": "鈴木 彩",
        "apply_date": "2026-11-02",
        "depart_date": "2026-11-16",
        "return_date": "2026-11-18",
        "nights": 2,
        "destination": "福岡",
        "amount": 62000,
        "items": [
            {"name": "航空券（往復）", "category": "交通費", "amount": 40000},
            {"name": "ホテル 2 泊", "category": "宿泊費", "amount": 22000},
        ],
        "purpose": "九州支店の在庫監査",
        "approver_position": "課長",
        "attachments": [],
    }


@pytest.fixture
def ringi():
    """不備のない稟議（30 万円・部長決裁・見積書あり）。"""
    return {
        "type": "ringi",
        "applicant": "高橋 誠",
        "apply_date": "2026-11-04",
        "amount": 300000,
        "items": [{"name": "ノート PC 2 台", "category": "備品", "amount": 300000}],
        "purpose": "新入社員 2 名の業務用端末の購入",
        "approver_position": "部長",
        "attachments": ["見積書"],
    }


def rules_of(findings):
    return sorted(f["rule"] for f in findings)


# --- 不備なし ---


@pytest.mark.parametrize("name", ["keihi", "shucchou", "ringi"])
def test_valid_application_has_no_findings(name, request):
    assert check(request.getfixturevalue(name)) == []


# --- R1 金額上限 ---


def test_r1_meeting_over_per_person_limit(keihi):
    keihi["items"][0]["amount"] = keihi["amount"] = 20004  # 1 人 5,001 円
    f = check(keihi)
    assert rules_of(f) == ["R1"]
    assert f[0]["article"] == "経費規程 第5条第1項"
    assert "5,000" in f[0]["reason"]


def test_r1_meeting_exactly_at_limit_is_ok(keihi):
    keihi["items"][0]["amount"] = keihi["amount"] = 20000  # 1 人 5,000 円ちょうど
    assert check(keihi) == []


def test_r1_lodging_over_per_night_limit(shucchou):
    shucchou["items"][1]["amount"] = 26000  # 1 泊 13,000 円
    shucchou["amount"] = 66000
    f = check(shucchou)
    assert rules_of(f) == ["R1"]
    assert f[0]["article"] == "出張旅費規程 第6条"


def test_r1_lodging_exactly_at_limit_is_ok(shucchou):
    shucchou["items"][1]["amount"] = 24000
    shucchou["amount"] = 64000
    assert check(shucchou) == []


# --- R2 決裁者 ---


@pytest.mark.parametrize(
    "amount, approver, ok",
    [
        (99999, "課長", True),
        (100000, "課長", False),  # 10 万円ちょうどは部長決裁
        (100000, "部長", True),
        (999999, "部長", True),
        (1000000, "部長", False),  # 100 万円ちょうどは役員決裁
        (1000000, "役員", True),
        (50000, "部長", True),  # 上位者の決裁は問題なし
    ],
)
def test_r2_approver_tier(ringi, amount, approver, ok):
    ringi["amount"] = ringi["items"][0]["amount"] = amount
    ringi["approver_position"] = approver
    f = [x for x in check(ringi) if x["rule"] == "R2"]
    assert (f == []) is ok
    if not ok:
        assert f[0]["article"] == "決裁権限規程 第4条"


def test_r2_applies_to_keihi_and_shucchou(shucchou):
    shucchou["items"][0]["amount"] = 90000
    shucchou["amount"] = 112000
    assert rules_of(check(shucchou)) == ["R2"]


# --- R3 申請期限 ---


def test_r3_keihi_31_days_after_payment(keihi):
    keihi["pay_date"] = "2026-10-10"  # 31 日前
    f = check(keihi)
    assert rules_of(f) == ["R3"]
    assert f[0]["article"] == "経費規程 第8条"


def test_r3_keihi_30_days_is_ok(keihi):
    keihi["pay_date"] = "2026-10-11"  # 30 日前
    assert check(keihi) == []


def test_r3_shucchou_6_days_before_departure(shucchou):
    shucchou["apply_date"] = "2026-11-10"  # 出発 6 日前
    f = check(shucchou)
    assert rules_of(f) == ["R3"]
    assert f[0]["article"] == "出張旅費規程 第4条"


def test_r3_shucchou_7_days_is_ok(shucchou):
    shucchou["apply_date"] = "2026-11-09"  # 出発 7 日前
    assert check(shucchou) == []


# --- R4 必須添付 ---


def test_r4_keihi_without_receipt(keihi):
    keihi["attachments"] = []
    f = check(keihi)
    assert rules_of(f) == ["R4"]
    assert f[0]["article"] == "経費規程 第7条"


def test_r4_ringi_50000_without_quote(ringi):
    ringi["amount"] = ringi["items"][0]["amount"] = 50000
    ringi["approver_position"] = "課長"
    ringi["attachments"] = []
    f = check(ringi)
    assert rules_of(f) == ["R4"]
    assert f[0]["article"] == "決裁権限規程 第6条"


def test_r4_ringi_under_50000_needs_no_quote(ringi):
    ringi["amount"] = ringi["items"][0]["amount"] = 49999
    ringi["approver_position"] = "課長"
    ringi["attachments"] = []
    assert check(ringi) == []


# --- R5 記入漏れ ---


@pytest.mark.parametrize(
    "name, article",
    [
        ("keihi", "経費規程 第6条第1項"),
        ("shucchou", "出張旅費規程 第3条第1項"),
        ("ringi", "決裁権限規程 第5条第1項"),
    ],
)
def test_r5_blank_purpose(name, article, request):
    app = request.getfixturevalue(name)
    app["purpose"] = "  "
    f = check(app)
    assert rules_of(f) == ["R5"]
    assert f[0]["article"] == article


def test_r5_meeting_without_participants_skips_r1(keihi):
    """参加人数が無いと 1 人あたりの額を出せない。R1 は判定せず、記入漏れだけを指摘する。"""
    keihi["participants"] = None
    keihi["items"][0]["amount"] = keihi["amount"] = 90000
    f = check(keihi)
    assert rules_of(f) == ["R5"]
    assert f[0]["article"] == "経費規程 第5条第2項"


# --- R6 合計不一致 ---


def test_r6_total_mismatch(shucchou):
    shucchou["amount"] = 60000  # 明細の合計は 62,000 円
    f = check(shucchou)
    assert rules_of(f) == ["R6"]
    assert f[0]["article"] == "出張旅費規程 第3条第2項"
    assert "62,000" in f[0]["reason"] and "60,000" in f[0]["reason"]


# --- 複合・不変条件 ---


def test_multiple_findings_are_ordered_by_rule(keihi):
    keihi["attachments"] = []
    keihi["pay_date"] = "2026-09-01"
    keihi["items"][0]["amount"] = keihi["amount"] = 24000
    assert [f["rule"] for f in check(keihi)] == ["R1", "R3", "R4"]


def test_check_does_not_mutate_input(ringi):
    before = copy.deepcopy(ringi)
    check(ringi)
    assert ringi == before


def test_unknown_type_is_rejected():
    with pytest.raises(ValueError):
        check({"type": "kyuka"})
