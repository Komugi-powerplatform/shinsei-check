"""規程 v2 のフロー「Shinsei Check v2 HTTP」を組み立てて作る（答え合わせ用・HTTP 要求トリガー）。

    .venv/bin/python flows/build_v2.py [--dry-run]

v1 の flows/build.py の部品（式の組み立て・トリガー・作成手順）を使い、v2 で足した
宿泊上限の表引き・会議費のただし書き・R7 タクシー（行ごと）・R8 相見積を足す。
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "flows"), str(ROOT / "scripts")]

import build as b  # noqa: E402

b.RULES = json.loads((ROOT / "rules" / "rules.v2.json").read_text(encoding="utf-8"))
b.PROMPT_KEY = "prompt_id_v2"  # AI Builder プロンプト「Shinsei Extract v2」
R = b.RULES
R["R1"]["lodging_per_night"] = R["R1"]["lodging_table"]["一般"]  # v1 の部品が参照する。宿泊の判定は下で差し替える
NAME, DESC = "Shinsei Check v2 HTTP", "規程 v2 のルールで申請書を判定する（v2 サンプルの答え合わせ用）"


def digits(key: str, unit: str) -> str:
    """「2 泊」「5 名」のように単位つきで返ることがあるので、数字だけを取り出す。"""
    return f"@int(concat('0', replace(replace(string(coalesce({b.app(key)}, 0)), '{unit}', ''), ' ', '')))"


def variables() -> dict[str, str]:
    r1 = R["R1"]
    v = b.variables()
    dest = f"coalesce({b.app('destination')}, '')"
    metro = " , ".join(f"contains({dest}, '{c}')" for c in r1["metro_cities"])
    v["people"] = digits("participants", "名")
    v["nights"] = digits("nights", "泊")
    v["quotes"] = digits("quotes_count", "社")
    extra = {
        "external": f"@equals(coalesce({b.app('external_participants')}, ''), '有')",
        "meeting_limit": f"@if({b.v('external')}, {r1['meeting_per_person_external']}, {r1['meeting_per_person']})",
        "metro": f"@or({metro}, and(contains({dest}, '{r1['metro_tokyo_prefix']}'), endsWith({dest}, '{r1['metro_tokyo_suffix']}')))",
        "lodging_limit": (
            f"@add(if(equals({b.app('applicant_class')}, '管理職'), {r1['lodging_table']['管理職']}, {r1['lodging_table']['一般']}), "
            f"if({b.v('metro')}, {r1['lodging_metro_bonus']}, 0))"
        ),
    }
    # per_person・per_night は people・nights のあと、上限は external・metro のあとに置く
    tail = {k: v.pop(k) for k in ("per_person", "per_night")}
    return v | extra | tail


def findings() -> dict[str, str]:
    r1, r8 = R["R1"], R["R8"]
    f = b.findings()
    is_ = lambda t: f"equals({b.v('type')}, '{t}')"  # noqa: E731
    f["R1_meeting"] = b.finding(
        f"and({is_('keihi')}, greater({b.v('meeting')}, 0), greater({b.v('people')}, 0), greater({b.v('per_person')}, {b.v('meeting_limit')}))",
        "R1", f"if({b.v('external')}, {b.lit(r1['articles']['会議費_社外'])}, {b.lit(r1['articles']['会議費'])})",
        b.lit("会議費が 1 人あたり "), b.yen(b.v("per_person")), b.lit("で、上限の "), b.yen(b.v("meeting_limit")), b.lit("を超えています。"),
    )
    f["R1_lodging"] = b.finding(
        f"and({is_('shucchou')}, greater({b.v('lodging')}, 0), greater({b.v('nights')}, 0), greater({b.v('per_night')}, {b.v('lodging_limit')}))",
        "R1", b.lit(r1["articles"]["宿泊費"]),
        b.lit("宿泊費が 1 泊あたり "), b.yen(b.v("per_night")), b.lit("で、上限の "), b.yen(b.v("lodging_limit")), b.lit("を超えています。"),
    )
    f["R8"] = b.finding(
        f"and({is_('ringi')}, greaterOrEquals({b.v('amount')}, {r8['multi_quote_from']}), greater({b.v('quotes')}, 0), less({b.v('quotes')}, {r8['min_quotes']}))",
        "R8", b.lit(r8["article"]),
        b.yen(str(r8["multi_quote_from"])), b.lit(f"以上の稟議には {r8['min_quotes']} 社以上の見積書が必要ですが、"),
        f"string({b.v('quotes')})", b.lit(" 社分しかありません。"),
    )
    return f


def actions() -> dict:
    r7 = R["R7"]
    acts: dict[str, dict] = {}
    prev: str | None = None

    def add(name: str, body: dict) -> None:
        nonlocal prev
        acts[name] = body | {"runAfter": {prev: ["Succeeded"]} if prev else {}}
        prev = name

    add("Run_prompt", {"type": "OpenApiConnection", "inputs": {
        "parameters": {"recordId": b.PROMPT_ID, "item/requestv2/Document/base64Encoded": f"@{b.FILE_B64}"},
        "host": {"apiId": b.AIB_API, "connectionName": "shared_commondataserviceforapps", "operationId": "aibuilderpredict_customprompt"}}})
    add("Compose_app", {"type": "Compose", "inputs": "@json(outputs('Run_prompt')?['body/responsev2/predictionOutput/text'])"})
    b.missing_actions(add)
    for name, expr in variables().items():
        add(f"V_{name}", {"type": "Compose", "inputs": expr})
    fs = findings()
    for name, expr in fs.items():
        add(f"F_{name}", {"type": "Compose", "inputs": expr})
    first = [n for n in fs if n != "R8"]
    add("Compose_candidates", {"type": "Compose", "inputs": "@createArray(" + ", ".join(f"outputs('F_{n}')" for n in first) + ")"})
    add("Filter_findings", {"type": "Query", "inputs": {"from": "@outputs('Compose_candidates')", "where": "@not(equals(item(), null))"}})
    # R7: 理由の無い高額タクシーを行ごとに拾い、1 行 1 件の指摘にする
    add("Filter_taxi", {"type": "Query", "inputs": {
        "from": f"@coalesce({b.app('items')}, json('[]'))",
        "where": (f"@and(contains(coalesce(item()?['name'], ''), '{r7['taxi_keyword']}'), greater(coalesce(item()?['amount'], 0), {r7['taxi_reason_over']}), "
                  "equals(trim(coalesce(item()?['note'], '')), ''))")}})
    add("Select_taxi", {"type": "Select", "inputs": {"from": "@body('Filter_taxi')", "select": {
        "rule": "R7",
        "article": "@{" + b.by_type(r7["articles"]) + "}",
        "reason": ("@{concat('タクシー代 ', formatNumber(item()?['amount'], '#,0'), '円（', item()?['name'], '）は ', "
                   f"formatNumber({r7['taxi_reason_over']}, '#,0'), '円を超えていますが、備考に理由が記入されていません。')" + "}"),
    }}})
    add("Compose_r8", {"type": "Compose", "inputs": "@if(equals(outputs('F_R8'), null), json('[]'), createArray(outputs('F_R8')))"})
    add("Compose_findings", {"type": "Compose", "inputs": "@union(body('Filter_findings'), body('Select_taxi'), outputs('Compose_r8'))"})
    add("Compose_result", {"type": "Compose", "inputs": b.result_inputs("outputs('Compose_findings')")})
    acts["Respond"] = {"type": "Response", "kind": "Http", "inputs": {"statusCode": 200, "body": {"result": "@{string(outputs('Compose_result'))}"}},
                       "runAfter": {"Compose_result": ["Succeeded"]}}
    acts["Respond_unreadable"] = {"type": "Response", "kind": "Http", "inputs": {"statusCode": 200, "body": {
        "result": '{"status":"unreadable","missing":[],"extracted":null,"findings":[]}'}}, "runAfter": {"Compose_result": ["Failed", "Skipped", "TimedOut"]}}
    return acts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    definition = b.definition("Http") | {"actions": actions()}
    clientdata = {"properties": {"connectionReferences": b.CONN_REFS, "definition": definition}, "schemaVersion": "1.0.0.0"}
    out = ROOT / "flows" / "out" / "Shinsei_Check_v2_HTTP.clientdata.json"
    out.write_text(json.dumps(clientdata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[{NAME}] {len(definition['actions'])} actions -> {out.relative_to(ROOT)}")
    if not args.dry_run:
        from dataverse_client import Dataverse

        dv = Dataverse()
        wid = b.deploy(dv, NAME, clientdata, DESC)
        print(f"[{NAME}] activated workflow={wid} flow={dv.get(f'workflows({wid})?$select=resourceid')['resourceid']}")


if __name__ == "__main__":
    main()
