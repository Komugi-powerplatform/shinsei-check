"""申請書 1 件を規程のルールで判定する。

入力は抽出項目の dict、出力は指摘（rule・article・reason）のリスト。
サンプルの正解ラベルを作るのと、フロー実装の答え合わせに使う。
しきい値と条番号は rules/ のルール定義に置く。rules.json が規程 v1（R1〜R6）、
rules.v2.json が規程 v2（宿泊上限の表引き・会議費のただし書き・R7 タクシー・R8 相見積を追加）。
ルール定義に無いキーの判定は行わないので、同じ check() で両方を扱える。
"""

import json
from datetime import date
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"
TYPES = ("keihi", "shucchou", "ringi")


def load_rules(name: str = "rules.json") -> dict:
    return json.loads((RULES_DIR / name).read_text(encoding="utf-8"))


RULES = load_rules()


def _yen(n: float) -> str:
    return f"{round(n):,}円"


def _finding(rule: str, article: str, reason: str) -> dict:
    return {"rule": rule, "article": article, "reason": reason}


def _category_total(app: dict, category: str) -> int:
    return sum(i["amount"] for i in app.get("items", []) if i["category"] == category)


def is_metro(destination: str | None, r1: dict) -> bool:
    """出張先が大都市（東京 23 区・大阪市・名古屋市）か。"""
    d = destination or ""
    in_tokyo_ward = r1["metro_tokyo_prefix"] in d and d.endswith(r1["metro_tokyo_suffix"])
    return in_tokyo_ward or any(city in d for city in r1["metro_cities"])


def lodging_limit(app: dict, r1: dict) -> int:
    if "lodging_table" not in r1:
        return r1["lodging_per_night"]
    base = r1["lodging_table"].get(app.get("applicant_class"), r1["lodging_table"]["一般"])
    return base + (r1["lodging_metro_bonus"] if is_metro(app.get("destination"), r1) else 0)


def _r1_limit(app: dict, rules: dict) -> list[dict]:
    r = rules["R1"]
    out = []
    meeting = _category_total(app, "会議費")
    people = app.get("participants")
    if app["type"] == "keihi" and meeting and people:
        external = bool(app.get("external_participants")) and "meeting_per_person_external" in r
        limit = r["meeting_per_person_external"] if external else r["meeting_per_person"]
        per = meeting / people
        if per > limit:
            out.append(
                _finding(
                    "R1",
                    r["articles"]["会議費_社外" if external else "会議費"],
                    f"会議費が 1 人あたり {_yen(per)}で、上限の {_yen(limit)}を超えています。",
                )
            )
    lodging = _category_total(app, "宿泊費")
    nights = app.get("nights")
    if app["type"] == "shucchou" and lodging and nights:
        limit = lodging_limit(app, r)
        per = lodging / nights
        if per > limit:
            out.append(
                _finding(
                    "R1",
                    r["articles"]["宿泊費"],
                    f"宿泊費が 1 泊あたり {_yen(per)}で、上限の {_yen(limit)}を超えています。",
                )
            )
    return out


def required_approver(amount: int, rules: dict = RULES) -> str:
    for tier in rules["R2"]["tiers"]:
        if tier["under"] is None or amount < tier["under"]:
            return tier["position"]
    raise AssertionError("tiers の最後は under: null であること")


def _r2_approver(app: dict, rules: dict) -> list[dict]:
    r = rules["R2"]
    need = required_approver(app["amount"], rules)
    got = app.get("approver_position")
    if r["ranks"].get(got, 0) >= r["ranks"][need]:
        return []
    return [
        _finding(
            "R2",
            r["article"],
            f"申請金額 {_yen(app['amount'])}は{need}の決裁が必要ですが、決裁者が{got or '未記入'}になっています。",
        )
    ]


def _r3_deadline(app: dict, rules: dict) -> list[dict]:
    r = rules["R3"]
    applied = date.fromisoformat(app["apply_date"])
    if app["type"] == "keihi":
        days = (applied - date.fromisoformat(app["pay_date"])).days
        if days > r["keihi_days_after_pay"]:
            return [
                _finding(
                    "R3",
                    r["articles"]["keihi"],
                    f"支払日から {days} 日たっており、申請期限の {r['keihi_days_after_pay']} 日を過ぎています。",
                )
            ]
    if app["type"] == "shucchou":
        days = (date.fromisoformat(app["depart_date"]) - applied).days
        if days < r["shucchou_days_before_depart"]:
            return [
                _finding(
                    "R3",
                    r["articles"]["shucchou"],
                    f"出発の {days} 日前の申請で、期限の {r['shucchou_days_before_depart']} 日前を過ぎています。",
                )
            ]
    return []


def _r4_attachment(app: dict, rules: dict) -> list[dict]:
    r = rules["R4"]
    attached = app.get("attachments") or []
    if app["type"] == "keihi" and r["keihi_required"] not in attached:
        return [_finding("R4", r["articles"]["keihi"], f"{r['keihi_required']}が添付されていません。")]
    if app["type"] == "ringi" and app["amount"] >= r["ringi_quote_from"] and r["ringi_required"] not in attached:
        return [
            _finding(
                "R4",
                r["articles"]["ringi"],
                f"{_yen(r['ringi_quote_from'])}以上の稟議に必要な{r['ringi_required']}が添付されていません。",
            )
        ]
    return []


def _r5_blank(app: dict, rules: dict) -> list[dict]:
    r = rules["R5"]
    out = []
    if not (app.get("purpose") or "").strip():
        out.append(_finding("R5", r["articles"]["purpose"][app["type"]], "目的が記入されていません。"))
    if app["type"] == "keihi" and _category_total(app, "会議費") and not app.get("participants"):
        out.append(_finding("R5", r["articles"]["participants"], "会議費の参加人数が記入されていません。"))
    return out


def _r6_total(app: dict, rules: dict) -> list[dict]:
    total = sum(i["amount"] for i in app.get("items", []))
    if total == app["amount"]:
        return []
    return [
        _finding(
            "R6",
            rules["R6"]["articles"][app["type"]],
            f"明細の合計 {_yen(total)}と申請金額 {_yen(app['amount'])}が一致していません。",
        )
    ]


def _r7_taxi(app: dict, rules: dict) -> list[dict]:
    """理由の無い高額タクシーを、明細の行ごとに指摘する（規程 v2）。"""
    r = rules.get("R7")
    if not r or app["type"] not in r["articles"]:
        return []
    return [
        _finding(
            "R7",
            r["articles"][app["type"]],
            f"タクシー代 {_yen(i['amount'])}（{i['name']}）は {_yen(r['taxi_reason_over'])}を超えていますが、備考に理由が記入されていません。",
        )
        for i in app.get("items", [])
        if r["taxi_keyword"] in i["name"] and i["amount"] > r["taxi_reason_over"] and not (i.get("note") or "").strip()
    ]


def _r8_quotes(app: dict, rules: dict) -> list[dict]:
    """高額の稟議に見積書が 1 社分しか無い（規程 v2）。1 通も無いときは R4 に任せる。"""
    r = rules.get("R8")
    if not r or app["type"] != "ringi" or app["amount"] < r["multi_quote_from"]:
        return []
    count = app.get("quotes_count") or 0
    if count == 0 or count >= r["min_quotes"]:
        return []
    return [
        _finding(
            "R8",
            r["article"],
            f"{_yen(r['multi_quote_from'])}以上の稟議には {r['min_quotes']} 社以上の見積書が必要ですが、{count} 社分しかありません。",
        )
    ]


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def missing_required(app: dict) -> list[str]:
    """判定に必須なのに読み取れなかった項目の名前を返す。空でなければ判定せず「判定できない」とする。

    目的や決裁者の空欄は申請書の不備として指摘するので、ここには入れない。
    """
    missing = []
    if app.get("type") not in TYPES:
        missing.append("申請種別")
    if app.get("amount") is None:
        missing.append("申請金額")
    if not app.get("items"):
        missing.append("明細")
    if _blank(app.get("apply_date")):
        missing.append("申請日")
    if app.get("type") == "keihi" and _blank(app.get("pay_date")):
        missing.append("支払日")
    if app.get("type") == "shucchou" and _blank(app.get("depart_date")):
        missing.append("出発日")
    return missing


CHECKS = (_r1_limit, _r2_approver, _r3_deadline, _r4_attachment, _r5_blank, _r6_total, _r7_taxi, _r8_quotes)


def check(app: dict, rules: dict = RULES) -> list[dict]:
    """指摘をルール番号の順で返す。不備が無ければ空のリスト。"""
    if app.get("type") not in TYPES:
        raise ValueError(f"未対応の申請種別です: {app.get('type')!r}")
    return [f for fn in CHECKS for f in fn(app, rules)]
