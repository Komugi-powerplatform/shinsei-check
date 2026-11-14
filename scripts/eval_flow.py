"""フロー「Shinsei Check HTTP」に 20 件を通し、判定エンジンの期待値と比べる。

    .venv/bin/python scripts/eval_flow.py [--ids 01,03]

結果は docs/flow-results.json に書く。呼び出し URL は署名つきなので表示も保存もしない。
"""

import argparse
import base64
import json
import subprocess
import time
from pathlib import Path

import httpx

import settings

ROOT = Path(__file__).resolve().parents[1]
SETS = {
    "v1": {"flow": "flow_id_v1_http", "dir": ROOT / "samples", "out": "flow-results.json"},  # Shinsei Check HTTP
    "v2": {"flow": "flow_id_v2_http", "dir": ROOT / "samples" / "v2", "out": "flow-results-v2.json"},  # Shinsei Check v2 HTTP
}
BASE = ""  # main() で config.local.json の値から組み立てる


def flow_headers() -> dict:
    tok = subprocess.run(
        ["az", "account", "get-access-token", "--resource", "https://service.flow.microsoft.com/", "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout.strip()
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def callback_url(h: dict) -> str:
    r = httpx.post(f"{BASE}/triggers/manual/listCallbackUrl?api-version=2016-11-01", headers=h, json={}, timeout=60)
    r.raise_for_status()
    return r.json()["response"]["value"]


def last_failure(h: dict) -> str:
    runs = httpx.get(f"{BASE}/runs?api-version=2016-11-01&$top=1", headers=h, timeout=60).json().get("value", [])
    if not runs:
        return "実行履歴なし"
    out = []
    acts = httpx.get(f"{BASE}/runs/{runs[0]['name']}/actions?api-version=2016-11-01", headers=h, timeout=60).json().get("value", [])
    for a in acts:
        p = a["properties"]
        if p.get("status") == "Failed":
            detail = json.dumps(p.get("error") or {}, ensure_ascii=False)
            if p.get("outputsLink"):
                detail += " " + httpx.get(p["outputsLink"]["uri"], timeout=60).text[:500]
            out.append(f"{a['name']}: {detail[:700]}")
    return " | ".join(out) or runs[0]["properties"].get("status", "?")


def result_from_run(h: dict, start: str | None = None) -> tuple[dict, float]:
    """応答が届かなかったときに、実行履歴から同じ実行の判定結果を取り出す。start（HH:MM:SS・UTC）が無ければ最新の実行。"""
    from datetime import datetime

    runs = httpx.get(f"{BASE}/runs?api-version=2016-11-01&$top=50", headers=h, timeout=60).json()["value"]
    run = next(r for r in runs if start is None or r["properties"]["startTime"][11:19] == start)
    pr = run["properties"]
    if pr["status"] != "Succeeded":
        raise RuntimeError(f"実行が {pr['status']}")
    acts = httpx.get(f"{BASE}/runs/{run['name']}/actions?api-version=2016-11-01&$top=100", headers=h, timeout=60).json()["value"]
    link = next(a for a in acts if a["name"] == "Compose_result")["properties"]["outputsLink"]["uri"]
    t = lambda k: datetime.fromisoformat(pr[k][:19])  # noqa: E731
    return httpx.get(link, timeout=60).json(), (t("endTime") - t("startTime")).total_seconds()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--set", default="v1", choices=list(SETS))
    ap.add_argument("--file", help="cases.json に無いファイルを 1 件だけ流し、返ってきた結果をそのまま表示する")
    args = ap.parse_args()
    global BASE
    cfg = SETS[args.set]
    BASE = (f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{settings.get('environment_id')}"
            f"/flows/{settings.get(cfg['flow'])}")
    cases = json.loads((cfg["dir"] / "cases.json").read_text(encoding="utf-8"))
    if args.ids:
        cases = [c for c in cases if c["id"] in args.ids.split(",")]
    h = flow_headers()
    url = callback_url(h)
    if args.file:
        path = Path(args.file)
        r = httpx.post(url, json={"file": {"name": path.name, "contentBytes": base64.b64encode(path.read_bytes()).decode()}}, timeout=180)
        result = json.loads(r.json()["result"])
        print(json.dumps({k: result.get(k) for k in ("status", "missing", "findings")}, ensure_ascii=False, indent=2))
        print("amount:", (result.get("extracted") or {}).get("amount"))
        return
    results = []
    for c in cases:
        path = cfg["dir"] / "files" / c["file"]
        body = {"file": {"name": c["file"], "contentBytes": base64.b64encode(path.read_bytes()).decode()}}
        row = {"id": c["id"], "file": c["file"], "format": c["format"], "expected": c["expected"]}
        t0 = time.time()
        try:
            r = httpx.post(url, json=body, timeout=180)
            row["seconds"] = round(time.time() - t0, 1)
            row["http"] = r.status_code
            result = json.loads(r.json()["result"])
            row |= {"status": result["status"], "missing": result.get("missing", []), "findings": result["findings"], "extracted": result["extracted"]}
        except httpx.ReadTimeout:
            # フローは終わっているのに応答だけ届かないことがある。同じ実行の結果を履歴から読む
            try:
                result, row["seconds"] = result_from_run(h)
                row |= {"status": result["status"], "missing": result.get("missing", []), "findings": result["findings"],
                        "extracted": result["extracted"], "recovered": "応答が届かず、実行履歴から結果を取得"}
            except Exception as exc:
                row["error"] = f"ReadTimeout のあと履歴からも取れず: {type(exc).__name__}: {str(exc)[:200]}"
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {str(exc)[:200]} / {last_failure(h)}"
        rules = lambda fs: [f["rule"] for f in fs or []]  # noqa: E731
        row["rules_ok"] = "findings" in row and rules(row["findings"]) == rules(c["expected"])
        row["exact_ok"] = row.get("findings") == c["expected"]
        results.append(row)
        print(c["id"], c["format"], "OK" if row["rules_ok"] else "NG", "文面一致" if row["exact_ok"] else "文面差", row.get("seconds"),
              rules(row.get("findings")), row.get("error", ""), row.get("recovered", ""),
              f"判定できない（読めなかった項目: {'・'.join(row.get('missing') or []) or '不明'}）" if row.get("status") == "unreadable" else "")
        if not row["exact_ok"] and row["rules_ok"]:
            for got, exp in zip(row["findings"], c["expected"]):
                if got != exp:
                    print("   フロー:", got, "\n   期待  :", exp)
    if not args.ids:
        (ROOT / "docs" / cfg["out"]).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    done = [r for r in results if "seconds" in r]
    print(f"判定できない {sum(r.get('status') == 'unreadable' for r in results)} 件")
    print(f"ルール一致 {sum(r['rules_ok'] for r in results)}/{len(results)}  条番号・理由まで一致 {sum(r['exact_ok'] for r in results)}/{len(results)}  "
          f"平均 {sum(r['seconds'] for r in done) / max(len(done), 1):.1f} 秒")


if __name__ == "__main__":
    main()
