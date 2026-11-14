"""AI Builder のプロンプト「Shinsei Extract」に 20 件を通し、真値と比べる。

    .venv/bin/python scripts/eval_extract.py [--ids 01,03]

結果は docs/extract-results.json に書く。判定に使う項目だけを比べ、
読み取った値を判定エンジンに通した指摘が期待と一致するかも見る。
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

import settings  # noqa: E402
from dataverse_client import Dataverse  # noqa: E402
from shinsei.rules import check  # noqa: E402

SOURCE = json.dumps(
    {"consumptionSource": "PowerAutomate", "partnerSource": "AIBuilder", "consumptionSourceVersion": "PowerAutomate"}
)
# 判定エンジンが使う項目（種別ごと）
KEYS = {
    "keihi": ["type", "apply_date", "pay_date", "amount", "items", "participants", "purpose", "approver_position", "attachments"],
    "shucchou": ["type", "apply_date", "depart_date", "nights", "amount", "items", "purpose", "approver_position"],
    "ringi": ["type", "apply_date", "amount", "items", "purpose", "approver_position", "attachments"],
}


def predict(dv: Dataverse, path: Path) -> tuple[dict, dict]:
    body = {
        "version": "2.0",
        "source": SOURCE,
        "requestv2": {
            "@odata.type": "#Microsoft.Dynamics.CRM.expando",
            "Document": {
                "@odata.type": "#Microsoft.Dynamics.CRM.expando",
                "base64Encoded": base64.b64encode(path.read_bytes()).decode(),
            },
        },
    }
    t0 = time.time()
    res = dv.request("POST", f"msdyn_aimodels({settings.get('prompt_id_v1')})/Microsoft.Dynamics.CRM.Predict", body, ok=(200,))
    out = res.json()["responsev2"]["predictionOutput"]
    meta = {"seconds": round(time.time() - t0, 1), "copilot_credits": out.get("costAsCopilotCredits"), "model": out.get("modelName")}
    return json.loads(out["text"]), meta


def normalize(raw: dict) -> dict:
    """プロンプトの出力を、判定エンジンが受け取る形にそろえる。"""
    app = dict(raw)
    app["attachments"] = [a["item"] if isinstance(a, dict) else a for a in (raw.get("attachments") or [])]
    for k in ("amount", "participants", "nights"):
        if isinstance(app.get(k), float):
            app[k] = int(app[k])
    app["items"] = [
        {"name": i.get("name"), "category": i.get("category"), "amount": int(i["amount"])} for i in (raw.get("items") or [])
    ]
    app["purpose"] = (app.get("purpose") or "").strip()
    app["participants"] = app.get("participants") or None
    return app


def diff_fields(truth: dict, got: dict) -> list[str]:
    bad = []
    for k in KEYS[truth["type"]]:
        t, g = truth.get(k), got.get(k)
        if k == "items":
            t = [(i["category"], i["amount"]) for i in t]
            g = [(i["category"], i["amount"]) for i in g]
        if k == "attachments":
            t, g = sorted(t), sorted(g)
        if k == "purpose":  # 判定は空欄かどうかだけを見る（空白や全角の差は数えない）
            t, g = bool(t.strip()), bool(g.strip())
        if t != g:
            bad.append(f"{k}: 正 {t!r} / 読み取り {g!r}")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--replay", action="store_true", help="保存済みの読み取り結果を使い、API を呼ばずに比べ直す")
    args = ap.parse_args()
    cases = json.loads((ROOT / "samples" / "cases.json").read_text(encoding="utf-8"))
    if args.ids:
        cases = [c for c in cases if c["id"] in args.ids.split(",")]
    saved = {}
    if args.replay:
        saved = {r["id"]: r for r in json.loads((ROOT / "docs" / "extract-results.json").read_text(encoding="utf-8"))}
    dv = None if args.replay else Dataverse()
    results = []
    for c in cases:
        row = {"id": c["id"], "file": c["file"], "format": c["format"], "expected": [f["rule"] for f in c["expected"]]}
        try:
            if args.replay:
                old = saved[c["id"]]
                raw, meta = old["raw"], {k: old.get(k) for k in ("seconds", "copilot_credits", "model")}
            else:
                raw, meta = predict(dv, ROOT / "samples" / "files" / c["file"])
            app = normalize(raw)
            row |= {"raw": raw, **meta, "field_errors": diff_fields(c["app"], app)}
            try:
                row["findings"] = [f["rule"] for f in check(app)]
            except Exception as exc:  # 読み取りが崩れて判定できない
                row["findings"], row["check_error"] = None, f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        row["ok"] = row.get("findings") == row["expected"]
        results.append(row)
        print(c["id"], c["format"], "OK" if row["ok"] else "NG", row.get("seconds"), row.get("findings"), row.get("field_errors") or row.get("error") or "")
    if not args.ids:
        (ROOT / "docs" / "extract-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    done = [r for r in results if "seconds" in r]
    print(f"\n判定一致 {sum(r['ok'] for r in results)}/{len(results)}  項目の読み違いあり {sum(bool(r.get('field_errors')) for r in results)} 件  "
          f"平均 {sum(r['seconds'] for r in done) / max(len(done), 1):.1f} 秒  クレジット計 {sum(r.get('copilot_credits') or 0 for r in done):.1f}")


if __name__ == "__main__":
    main()
