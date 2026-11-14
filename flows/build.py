"""申請チェックのフロー定義を組み立て、Dataverse の workflow テーブルへ直接作る。

    .venv/bin/python flows/build.py            # 2 本を作成・更新して有効化
    .venv/bin/python flows/build.py --dry-run  # flows/out/ に定義を書くだけ

2 本のフローは同じアクションを持ち、トリガーと応答だけが違う。
- Shinsei Check       : Copilot Studio のエージェントから呼ぶ（Skills トリガー）
- Shinsei Check HTTP  : 20 件の答え合わせ用（HTTP 要求トリガー）
しきい値と条番号は rules/rules.json から読み、式に埋め込む。
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
RULES = json.loads((ROOT / "rules" / "rules.json").read_text(encoding="utf-8"))

# flows/out/ に書く定義には環境の ID を入れず、置き場所だけを書く。実際の値は作成のときに config.local.json から入れる
PROMPT_ID = "<AI_BUILDER_PROMPT_ID>"  # AI Builder プロンプト「Shinsei Extract」
PROMPT_KEY = "prompt_id_v1"
CONN_REF = "<CONNECTION_REFERENCE_LOGICAL_NAME>"
AIB_API = "providers/Microsoft.ProcessSimple/operationGroups/aibuilder"
CONN_REFS = {
    "shared_commondataserviceforapps": {
        "runtimeSource": "embedded",
        "connection": {"connectionReferenceLogicalName": CONN_REF},
        "api": {"name": "shared_commondataserviceforapps"},
    }
}
FILE_B64 = "triggerBody()?['file']?['contentBytes']"
DAY_TICKS = 864000000000


# --- 式の部品。if() と and() は両方の枝を評価する前提で、どの式も null や空欄で落ちないように書く ---


def app(key: str) -> str:
    return f"outputs('Compose_app')?['{key}']"


def v(name: str) -> str:
    return f"outputs('V_{name}')"


def lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def yen(expr: str) -> str:
    return f"concat(formatNumber({expr}, '#,0'), '円')"


def date(key: str) -> str:
    return f"if(empty({app(key)}), '2000-01-01', {app(key)})"


def by_type(articles: dict) -> str:
    return (
        f"if(equals({v('type')}, 'keihi'), {lit(articles.get('keihi', ''))}, "
        f"if(equals({v('type')}, 'shucchou'), {lit(articles.get('shucchou', ''))}, {lit(articles.get('ringi', ''))}))"
    )


def finding(cond: str, rule: str, article: str, *reason: str) -> str:
    """条件が真なら指摘の JSON、偽なら null を返す式。article と reason は式で渡す。"""
    parts = ", ".join(reason)
    return (
        f"@if({cond}, json(concat('{{\"rule\":\"{rule}\",\"article\":\"', {article}, "
        f"'\",\"reason\":\"', {parts}, '\"}}')), null)"
    )


def variables() -> dict[str, str]:
    r1, r2 = RULES["R1"], RULES["R2"]
    t1, t2 = r2["tiers"][0]["under"], r2["tiers"][1]["under"]
    items_xml = f"xml(json(concat('{{\"r\":{{\"i\":', string(coalesce({app('items')}, json('[]'))), '}}}}')))"
    return {
        "type": f"@coalesce({app('type')}, '')",
        "amount": f"@coalesce({app('amount')}, 0)",
        "total": f"@xpath({items_xml}, 'sum(/r/i/amount)')",
        "meeting": f"@xpath({items_xml}, 'sum(/r/i[category=\"会議費\"]/amount)')",
        "lodging": f"@xpath({items_xml}, 'sum(/r/i[category=\"宿泊費\"]/amount)')",
        "people": f"@coalesce({app('participants')}, 0)",
        # 「1泊」のように文字で返ることがあるので、数字だけを取り出す
        "nights": f"@int(concat('0', replace(replace(string(coalesce({app('nights')}, 0)), '泊', ''), ' ', '')))",
        "need": f"@if(less({v('amount')}, {t1}), 1, if(less({v('amount')}, {t2}), 2, 3))",
        "got": (
            f"@if(equals({app('approver_position')}, '課長'), 1, if(equals({app('approver_position')}, '部長'), 2, "
            f"if(equals({app('approver_position')}, '役員'), 3, 0)))"
        ),
        "days_after_pay": f"@div(sub(ticks({date('apply_date')}), ticks({date('pay_date')})), {DAY_TICKS})",
        "days_before_depart": f"@div(sub(ticks({date('depart_date')}), ticks({date('apply_date')})), {DAY_TICKS})",
        "attached": f"@string(coalesce({app('attachments')}, json('[]')))",
        "purpose": f"@trim(coalesce({app('purpose')}, ''))",
        "per_person": f"@div(float({v('meeting')}), max({v('people')}, 1))",
        "per_night": f"@div(float({v('lodging')}), max({v('nights')}, 1))",
    }


def findings() -> dict[str, str]:
    r1, r2, r3, r4, r5, r6 = (RULES[k] for k in ("R1", "R2", "R3", "R4", "R5", "R6"))
    is_ = lambda t: f"equals({v('type')}, '{t}')"  # noqa: E731
    need_name = f"if(equals({v('need')}, 1), '課長', if(equals({v('need')}, 2), '部長', '役員'))"
    return {
        "R1_meeting": finding(
            f"and({is_('keihi')}, greater({v('meeting')}, 0), greater({v('people')}, 0), "
            f"greater({v('per_person')}, {r1['meeting_per_person']}))",
            "R1", lit(r1["articles"]["会議費"]),
            lit("会議費が 1 人あたり "), yen(v("per_person")), lit("で、上限の "), yen(str(r1["meeting_per_person"])), lit("を超えています。"),
        ),
        "R1_lodging": finding(
            f"and({is_('shucchou')}, greater({v('lodging')}, 0), greater({v('nights')}, 0), "
            f"greater({v('per_night')}, {r1['lodging_per_night']}))",
            "R1", lit(r1["articles"]["宿泊費"]),
            lit("宿泊費が 1 泊あたり "), yen(v("per_night")), lit("で、上限の "), yen(str(r1["lodging_per_night"])), lit("を超えています。"),
        ),
        "R2": finding(
            f"less({v('got')}, {v('need')})",
            "R2", lit(r2["article"]),
            lit("申請金額 "), yen(v("amount")), lit("は"), need_name, lit("の決裁が必要ですが、決裁者が"),
            f"if(empty({app('approver_position')}), '未記入', {app('approver_position')})", lit("になっています。"),
        ),
        "R3_keihi": finding(
            f"and({is_('keihi')}, greater({v('days_after_pay')}, {r3['keihi_days_after_pay']}))",
            "R3", lit(r3["articles"]["keihi"]),
            lit("支払日から "), f"string({v('days_after_pay')})", lit(f" 日たっており、申請期限の {r3['keihi_days_after_pay']} 日を過ぎています。"),
        ),
        "R3_shucchou": finding(
            f"and({is_('shucchou')}, less({v('days_before_depart')}, {r3['shucchou_days_before_depart']}))",
            "R3", lit(r3["articles"]["shucchou"]),
            lit("出発の "), f"string({v('days_before_depart')})", lit(f" 日前の申請で、期限の {r3['shucchou_days_before_depart']} 日前を過ぎています。"),
        ),
        "R4_keihi": finding(
            f"and({is_('keihi')}, not(contains({v('attached')}, '{r4['keihi_required']}')))",
            "R4", lit(r4["articles"]["keihi"]), lit(f"{r4['keihi_required']}が添付されていません。"),
        ),
        "R4_ringi": finding(
            f"and({is_('ringi')}, greaterOrEquals({v('amount')}, {r4['ringi_quote_from']}), "
            f"not(contains({v('attached')}, '{r4['ringi_required']}')))",
            "R4", lit(r4["articles"]["ringi"]),
            yen(str(r4["ringi_quote_from"])), lit(f"以上の稟議に必要な{r4['ringi_required']}が添付されていません。"),
        ),
        "R5_purpose": finding(
            f"equals({v('purpose')}, '')", "R5", by_type(r5["articles"]["purpose"]), lit("目的が記入されていません。"),
        ),
        "R5_people": finding(
            f"and({is_('keihi')}, greater({v('meeting')}, 0), equals({v('people')}, 0))",
            "R5", lit(r5["articles"]["participants"]), lit("会議費の参加人数が記入されていません。"),
        ),
        "R6": finding(
            f"or(greater({v('total')}, {v('amount')}), less({v('total')}, {v('amount')}))",
            "R6", by_type(r6["articles"]),
            lit("明細の合計 "), yen(v("total")), lit("と申請金額 "), yen(v("amount")), lit("が一致していません。"),
        ),
    }


def missing_actions(add) -> None:
    """判定に必須の値を読めたかを、金額や日付を使う計算より前に確かめる（src/shinsei/rules.py の missing_required と同じ条件）。"""
    blank = lambda key: f"empty(trim(coalesce({app(key)}, '')))"  # noqa: E731
    kind = f"coalesce({app('type')}, '')"
    conds = {
        "申請種別": f"not(contains(createArray('keihi', 'shucchou', 'ringi'), {kind}))",
        "申請金額": f"equals({app('amount')}, null)",
        "明細": f"empty(coalesce({app('items')}, json('[]')))",
        "申請日": blank("apply_date"),
        "支払日": f"and(equals({kind}, 'keihi'), {blank('pay_date')})",
        "出発日": f"and(equals({kind}, 'shucchou'), {blank('depart_date')})",
    }
    add("Compose_missing_candidates", {"type": "Compose", "inputs":
        "@createArray(" + ", ".join(f"if({c}, '{label}', null)" for label, c in conds.items()) + ")"})
    add("Filter_missing", {"type": "Query", "inputs": {"from": "@outputs('Compose_missing_candidates')", "where": "@not(equals(item(), null))"}})


def result_inputs(findings_expr: str) -> dict:
    """読めなかった項目が 1 つでもあれば、0 や空として判定した指摘は返さず「判定できない」を返す。"""
    readable = "equals(length(body('Filter_missing')), 0)"
    return {
        "status": f"@{{if({readable}, 'checked', 'unreadable')}}",
        "missing": "@body('Filter_missing')",
        "extracted": "@outputs('Compose_app')",
        "findings": f"@if({readable}, {findings_expr}, json('[]'))",
    }


def actions(response_kind: str) -> dict:
    acts: dict[str, dict] = {}
    prev: str | None = None

    def add(name: str, body: dict) -> None:
        nonlocal prev
        acts[name] = body | {"runAfter": {prev: ["Succeeded"]} if prev else {}}
        prev = name

    add("Run_prompt", {
        "type": "OpenApiConnection",
        "inputs": {
            "parameters": {"recordId": PROMPT_ID, "item/requestv2/Document/base64Encoded": f"@{FILE_B64}"},
            "host": {"apiId": AIB_API, "connectionName": "shared_commondataserviceforapps", "operationId": "aibuilderpredict_customprompt"},
        },
    })
    add("Compose_app", {"type": "Compose", "inputs": "@json(outputs('Run_prompt')?['body/responsev2/predictionOutput/text'])"})
    missing_actions(add)
    for name, expr in variables().items():
        add(f"V_{name}", {"type": "Compose", "inputs": expr})
    names = list(findings())
    for name, expr in findings().items():
        add(f"F_{name}", {"type": "Compose", "inputs": expr})
    add("Compose_candidates", {"type": "Compose", "inputs": "@createArray(" + ", ".join(f"outputs('F_{n}')" for n in names) + ")"})
    add("Filter_findings", {"type": "Query", "inputs": {"from": "@outputs('Compose_candidates')", "where": "@not(equals(item(), null))"}})
    add("Compose_result", {"type": "Compose", "inputs": result_inputs("body('Filter_findings')")})
    schema = {"type": "object", "properties": {"result": {
        "title": "result", "description": "判定結果（JSON 文字列。status・extracted・findings）",
        "type": "string", "x-ms-content-hint": "TEXT", "x-ms-dynamically-added": True}}, "additionalProperties": {}}
    respond = {"type": "Response", "kind": response_kind, "inputs": {"statusCode": 200}}
    if response_kind == "Skills":
        respond["inputs"]["schema"] = schema
    acts["Respond"] = {**respond, "runAfter": {"Compose_result": ["Succeeded"]}}
    acts["Respond"]["inputs"] = respond["inputs"] | {"body": {"result": "@{string(outputs('Compose_result'))}"}}
    acts["Respond_unreadable"] = {**respond, "runAfter": {"Compose_result": ["Failed", "Skipped", "TimedOut"]}}
    acts["Respond_unreadable"]["inputs"] = respond["inputs"] | {
        "body": {"result": '{"status":"unreadable","missing":[],"extracted":null,"findings":[]}'}}
    return acts


FILE_SCHEMA = {
    "title": "file", "description": "ユーザーが添付した申請書ファイル", "type": "object",
    "x-ms-content-hint": "FILE", "x-ms-dynamically-added": True,
    "properties": {"name": {"type": "string"}, "contentBytes": {"type": "string", "format": "byte"}},
}


def trigger(kind: str) -> dict:
    inputs: dict = {"schema": {"type": "object", "properties": {"file": FILE_SCHEMA}, "required": ["file"]}}
    if kind == "Http":
        inputs["triggerAuthenticationType"] = "All"
    return {"manual": {"type": "Request", "kind": kind, "inputs": inputs}}


def definition(kind: str) -> dict:
    return {
        "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {"$authentication": {"defaultValue": {}, "type": "SecureObject"}, "$connections": {"defaultValue": {}, "type": "Object"}},
        "triggers": trigger(kind),
        "actions": actions(kind),
    }


FLOWS = {
    "Shinsei Check": ("Skills", "添付された申請書を読み取り、規程のルールで判定して指摘を返す（エージェント用）"),
    "Shinsei Check HTTP": ("Http", "Shinsei Check と同じ判定を HTTP 要求で呼ぶ（20 件の答え合わせ用）"),
}


def deploy(dv, name: str, clientdata: dict, desc: str) -> str:
    existing = dv.get(f"workflows?$select=workflowid,statecode&$filter=name eq '{name}' and category eq 5")["value"]
    import settings

    data = (json.dumps(clientdata, ensure_ascii=False)
            .replace(PROMPT_ID, settings.get(PROMPT_KEY)).replace(CONN_REF, settings.get("connection_reference")))
    if existing:
        wid = existing[0]["workflowid"]
        if existing[0].get("statecode") != 0:
            dv.request("PATCH", f"workflows({wid})", {"statecode": 0, "statuscode": 1}, ok=(204,))
        dv.request("PATCH", f"workflows({wid})", {"clientdata": data, "description": desc}, ok=(204,))
    else:
        r = dv.request("POST", "workflows", {"name": name, "description": desc, "category": 5, "type": 1,
                                             "primaryentity": "none", "clientdata": data}, ok=(201, 204))
        wid = r.headers["OData-EntityId"].rsplit("(", 1)[1].rstrip(")")
    dv.request("PATCH", f"workflows({wid})", {"statecode": 1, "statuscode": 2}, ok=(204,))
    return wid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    dv = None
    if not args.dry_run:
        from dataverse_client import Dataverse

        dv = Dataverse()
    for name, (kind, desc) in FLOWS.items():
        if args.only and name not in args.only:
            continue
        clientdata = {"properties": {"connectionReferences": CONN_REFS, "definition": definition(kind)}, "schemaVersion": "1.0.0.0"}
        out = ROOT / "flows" / "out" / f"{name.replace(' ', '_')}.clientdata.json"
        out.write_text(json.dumps(clientdata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{name}] {len(clientdata['properties']['definition']['actions'])} actions -> {out.relative_to(ROOT)}")
        if dv:
            wid = deploy(dv, name, clientdata, desc)
            rid = dv.get(f"workflows({wid})?$select=resourceid")["resourceid"]
            print(f"[{name}] activated workflow={wid} flow={rid}")


if __name__ == "__main__":
    main()
