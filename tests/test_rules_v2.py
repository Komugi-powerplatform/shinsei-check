"""規程 v2 のルール（表引き・ただし書き・行ごとの判定・相見積）の受入条件。"""

import pytest

from shinsei.rules import check, load_rules

V2 = load_rules("rules.v2.json")


def rules_of(findings):
    return sorted(f["rule"] for f in findings)


@pytest.fixture
def keihi():
    return {
        "type": "keihi", "applicant": "佐藤 健二", "applicant_class": "一般",
        "apply_date": "2026-11-10", "pay_date": "2026-11-05", "amount": 16000,
        "items": [{"name": "打合せ昼食", "category": "会議費", "amount": 16000, "note": ""}],
        "participants": 4, "external_participants": False, "purpose": "販促計画の打合せ",
        "approver_position": "課長", "attachments": ["領収書"],
    }


@pytest.fixture
def shucchou():
    return {
        "type": "shucchou", "applicant": "鈴木 彩", "applicant_class": "一般",
        "apply_date": "2026-11-02", "depart_date": "2026-11-16", "return_date": "2026-11-18",
        "nights": 2, "destination": "福岡市", "amount": 62000,
        "items": [
            {"name": "航空券（往復）", "category": "交通費", "amount": 40000, "note": ""},
            {"name": "ホテル 2 泊", "category": "宿泊費", "amount": 22000, "note": ""},
        ],
        "purpose": "九州支店の在庫監査", "approver_position": "課長", "attachments": [],
    }


@pytest.fixture
def ringi():
    return {
        "type": "ringi", "applicant": "高橋 誠", "applicant_class": "一般", "apply_date": "2026-11-04",
        "amount": 300000, "items": [{"name": "ノート PC 2 台", "category": "備品", "amount": 300000, "note": ""}],
        "purpose": "新入社員の端末の購入", "approver_position": "部長",
        "attachments": ["見積書"], "quotes_count": 1,
    }


@pytest.mark.parametrize("name", ["keihi", "shucchou", "ringi"])
def test_valid_applications(name, request):
    assert check(request.getfixturevalue(name), V2) == []


# --- 宿泊上限の表引き（役職区分 × 地域区分） ---

@pytest.mark.parametrize(
    "klass, dest, per_night, ok",
    [
        ("一般", "福岡市", 12000, True),
        ("一般", "福岡市", 12001, False),
        ("管理職", "福岡市", 15000, True),
        ("管理職", "福岡市", 15001, False),
        ("一般", "大阪市", 15000, True),  # 一般 12,000 ＋ 大都市 3,000
        ("一般", "大阪市", 15001, False),
        ("管理職", "名古屋市", 18000, True),
        ("管理職", "名古屋市", 18001, False),
        ("一般", "東京都千代田区", 15000, True),  # 23 区内
        ("一般", "東京都八王子市", 12001, False),  # 東京都でも 23 区外は加算なし
        ("一般", "大阪府堺市", 12001, False),  # 大阪府でも大阪市でなければ加算なし
    ],
)
def test_lodging_limit_table(shucchou, klass, dest, per_night, ok):
    shucchou["applicant_class"], shucchou["destination"], shucchou["nights"] = klass, dest, 1
    shucchou["items"][1]["amount"] = per_night
    shucchou["amount"] = 40000 + per_night
    f = [x for x in check(shucchou, V2) if x["rule"] == "R1"]
    assert (f == []) is ok
    if not ok:
        assert f[0]["article"] == "出張旅費規程 第6条"


def test_lodging_reason_names_the_limit_used(shucchou):
    shucchou["applicant_class"], shucchou["destination"] = "管理職", "大阪市"
    shucchou["items"][1]["amount"] = 38000  # 1 泊 19,000 円、上限 18,000 円
    shucchou["amount"] = 78000
    f = check(shucchou, V2)
    assert rules_of(f) == ["R1"]
    assert "19,000" in f[0]["reason"] and "18,000" in f[0]["reason"]


# --- 会議費のただし書き（社外参加者ありは 8,000 円） ---

@pytest.mark.parametrize(
    "external, per_person, ok, article",
    [
        (False, 5000, True, None),
        (False, 5001, False, "経費規程 第5条第1項"),
        (True, 7900, True, None),
        (True, 8000, True, None),
        (True, 8001, False, "経費規程 第5条第2項"),
    ],
)
def test_meeting_limit_with_external(keihi, external, per_person, ok, article):
    keihi["external_participants"] = external
    keihi["items"][0]["amount"] = keihi["amount"] = per_person * 4
    f = [x for x in check(keihi, V2) if x["rule"] == "R1"]
    assert (f == []) is ok
    if not ok:
        assert f[0]["article"] == article


def test_participants_blank_uses_v2_article(keihi):
    keihi["participants"] = None
    f = check(keihi, V2)
    assert rules_of(f) == ["R5"] and f[0]["article"] == "経費規程 第5条第3項"


# --- R7 タクシーの理由（行ごと） ---

def taxi(amount, note=""):
    return {"name": "タクシー（駅〜取引先）", "category": "交通費", "amount": amount, "note": note}


@pytest.mark.parametrize(
    "amount, note, ok", [(5000, "", True), (5001, "", False), (5001, "終電後のため", True), (9800, "  ", False)]
)
def test_r7_taxi_reason(keihi, amount, note, ok):
    keihi["items"].append(taxi(amount, note))
    keihi["amount"] += amount
    f = [x for x in check(keihi, V2) if x["rule"] == "R7"]
    assert (f == []) is ok
    if not ok:
        assert f[0]["article"] == "経費規程 第9条" and f"{amount:,}" in f[0]["reason"]


def test_r7_one_finding_per_row_and_shucchou_article(shucchou):
    shucchou["items"] += [taxi(6000), taxi(7000, "荷物が多いため"), taxi(8000)]
    shucchou["amount"] += 21000
    f = [x for x in check(shucchou, V2) if x["rule"] == "R7"]
    assert len(f) == 2
    assert {x["article"] for x in f} == {"出張旅費規程 第5条第2項"}


def test_r7_ignores_non_taxi_transport(keihi):
    keihi["items"].append({"name": "新幹線（東京〜名古屋）", "category": "交通費", "amount": 11000, "note": ""})
    keihi["amount"] += 11000
    assert check(keihi, V2) == []


# --- R8 相見積 ---

@pytest.mark.parametrize(
    "amount, quotes, ok", [(999999, 1, True), (1000000, 1, False), (1000000, 2, True), (3000000, 3, True)]
)
def test_r8_multiple_quotes(ringi, amount, quotes, ok):
    ringi["amount"] = ringi["items"][0]["amount"] = amount
    ringi["approver_position"] = "役員"
    ringi["quotes_count"] = quotes
    f = [x for x in check(ringi, V2) if x["rule"] == "R8"]
    assert (f == []) is ok
    if not ok:
        assert f[0]["article"] == "決裁権限規程 第6条第2項"


def test_no_quote_at_all_is_r4_only(ringi):
    """見積書が 1 通も無いときは添付漏れ（R4）だけを出し、相見積（R8）を重ねない。"""
    ringi["amount"] = ringi["items"][0]["amount"] = 1500000
    ringi["approver_position"] = "役員"
    ringi["attachments"], ringi["quotes_count"] = [], 0
    f = check(ringi, V2)
    assert rules_of(f) == ["R4"] and f[0]["article"] == "決裁権限規程 第6条第1項"


def test_v1_rules_do_not_know_v2_rules(ringi):
    """v1 のルール定義では R7・R8 を判定しない。"""
    ringi["amount"] = ringi["items"][0]["amount"] = 1500000
    ringi["approver_position"] = "役員"
    assert check(ringi) == []
