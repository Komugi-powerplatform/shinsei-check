"""v2 サンプル（手書き風・2 ページ）の申請書ファイルと、規程 v2 の PDF を作る。

    PYTHONPATH=src .venv/bin/python -m shinsei.generate_v2

帳票は絶対座標で組む。印字する文字は reportlab、手書き風の記入は同じ座標に
Pillow とクレー体で重ねる（位置と傾きを少し揺らす）。形式は 4 つ。
- pdf2     : 文字つき PDF（明細が長く 2 ページ）
- scan2    : 2 ページをスキャン風にした PDF
- hw-scan  : 手書き風の記入をスキャン風にした PDF（1 ページ）
- hw-photo : 手書き風の記入を写真風にした JPG
手書き風フォントは本物の手書きより読みやすい。結果を「手書き」の精度として扱わないこと。
"""

import json
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from shinsei.generate import COMPANY, FONT, KITEI, ROOT, TITLES, build_kitei_dir, jp_date, photo_like, scan_like
from shinsei.rules import check, load_rules

SAMPLES = ROOT / "samples" / "v2"
FILES = SAMPLES / "files"
RULES_V2 = load_rules("rules.v2.json")
W, H = A4
LEFT, RIGHT = 50, W - 50
LABEL_W = 150
ROW_H, ITEM_H = 24, 20
COLS = [(LEFT, 205, "品名"), (LEFT + 205, 75, "費目"), (LEFT + 280, 85, "金額"), (LEFT + 365, RIGHT - LEFT - 365, "備考")]
FIRST_PAGE_ROWS, SINGLE_PAGE_ROWS = 14, 12
INK = (28, 38, 96)


def klee_path() -> str:
    out = subprocess.run(["fc-list", ":", "file"], capture_output=True, text=True, timeout=30).stdout
    for line in out.splitlines():
        if line.rstrip(": ").endswith("Klee.ttc"):
            return line.rstrip(": ")
    raise FileNotFoundError("クレー体（Klee.ttc）が見つかりません")


def yen(n: int) -> str:
    return f"{n:,} 円"


def header_rows(app: dict) -> list[tuple[str, str]]:
    rows = [("申請日", jp_date(app["apply_date"])), ("所属", app["department"]), ("申請者", app["applicant"]),
            ("役職区分", app["applicant_class"])]
    if app["type"] == "keihi":
        ext = app.get("external_participants")
        rows += [("支払日", jp_date(app["pay_date"])), ("目的", app["purpose"]),
                 ("参加人数（会議費のみ）", f"{app['participants']} 名" if app.get("participants") else ""),
                 ("社外の参加者（会議費のみ）", {True: "CHECK:有|無:0", False: "CHECK:有|無:1"}.get(ext, "CHECK:有|無:-"))]
    elif app["type"] == "shucchou":
        rows += [("出張先", app["destination"]), ("出発日", jp_date(app["depart_date"])),
                 ("帰着日", jp_date(app["return_date"])), ("宿泊数", f"{app['nights']} 泊"), ("目的", app["purpose"])]
    else:
        rows += [("件名", app["subject"]), ("目的", app["purpose"])]
    return rows


def footer_rows(app: dict) -> list[tuple[str, str]]:
    rows = [("申請金額（税込）", yen(app["amount"]))]
    name = {"keihi": "領収書", "ringi": "見積書"}.get(app["type"])
    if name:
        rows.append(("添付書類", f"CHECK:{name}:{0 if name in app['attachments'] else '-'}"))
    if app["type"] == "ringi":
        rows.append(("見積書の社数", f"{app['quotes_count']} 社" if app.get("quotes_count") else ""))
    rows.append(("決裁者", f"{app['approver_position']}　{app['approver_name']}"))
    return rows


def layout(app: dict) -> list[dict]:
    """ページごとの描画命令を返す。text の kind は label（印字）か value（記入）。"""
    items = app["items"]
    chunks = [items] if len(items) <= SINGLE_PAGE_ROWS else [items[:FIRST_PAGE_ROWS], items[FIRST_PAGE_ROWS:]]
    pages = []
    for pno, chunk in enumerate(chunks):
        ops = {"lines": [], "texts": [], "checks": []}
        y = H - 55

        def text(x, yy, s, kind, size=10.5, align="left"):
            ops["texts"].append({"x": x, "y": yy, "s": s, "kind": kind, "size": size, "align": align})

        def kv_table(rows, top):
            yy = top
            for label, value in rows:
                ops["lines"].append((LEFT, yy - ROW_H, RIGHT - LEFT, ROW_H, LEFT + LABEL_W))
                text(LEFT + 6, yy - 16, label, "label", 9.5)
                if value.startswith("CHECK:"):
                    _, names, picked = value.split(":")
                    x = LEFT + LABEL_W + 8
                    for i, n in enumerate(names.split("|")):
                        ops["checks"].append({"x": x, "y": yy - 17, "on": picked == str(i)})
                        text(x + 16, yy - 16, n, "label")
                        x += 70
                else:
                    text(LEFT + LABEL_W + 8, yy - 16, value, "value")
                yy -= ROW_H
            return yy

        text(RIGHT, y, COMPANY, "label", 9.5, "right")
        y -= 34
        text(W / 2, y, TITLES[app["type"]] + ("（続き）" if pno else ""), "label", 17, "center")
        y -= 22
        if pno == 0:
            y = kv_table(header_rows(app), y) - 26
        else:
            text(LEFT, y - 4, f"申請者: {app['applicant']}　申請日: {jp_date(app['apply_date'])}", "label", 9.5)
            y -= 30
        text(LEFT, y + 6, "明細" + ("（続き）" if pno else ""), "label", 11)
        for x, w, title in COLS:
            ops["lines"].append((x, y - ITEM_H, w, ITEM_H, None))
            text(x + 5, y - 14, title, "label", 9.5)
        y -= ITEM_H
        for it in chunk:
            for x, w, _ in COLS:
                ops["lines"].append((x, y - ITEM_H, w, ITEM_H, None))
            text(COLS[0][0] + 5, y - 14, it["name"], "value", 9.5)
            text(COLS[1][0] + 5, y - 14, it["category"], "value", 9.5)
            text(COLS[2][0] + COLS[2][1] - 6, y - 14, yen(it["amount"]), "value", 9.5, "right")
            text(COLS[3][0] + 5, y - 14, it.get("note") or "", "value", 8.5)
            y -= ITEM_H
        if pno < len(chunks) - 1:
            text(RIGHT, y - 16, "（明細は次のページへ続く）", "label", 9.5, "right")
        else:
            kv_table(footer_rows(app), y - 22)
        text(W / 2, 30, f"{pno + 1} / {len(chunks)}", "label", 9, "center")
        pages.append(ops)
    return pages


def draw_printed(c: canvas.Canvas, ops: dict, with_values: bool) -> None:
    c.setLineWidth(0.6)
    for x, y, w, h, split in ops["lines"]:
        c.rect(x, y, w, h)
        if split:
            c.setFillGray(0.92)
            c.rect(x, y, split - x, h, fill=1)
            c.setFillGray(0)
    for ck in ops["checks"]:
        c.rect(ck["x"], ck["y"], 10, 10, fill=1 if (with_values and ck["on"]) else 0)
    for t in ops["texts"]:
        if t["kind"] == "value" and not with_values:
            continue
        c.setFont(FONT, t["size"])
        draw = {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[t["align"]]
        draw(t["x"], t["y"], t["s"])


def build_pdf(app: dict, out: Path, with_values: bool) -> list[dict]:
    pages = layout(app)
    c = canvas.Canvas(str(out), pagesize=A4)
    for ops in pages:
        draw_printed(c, ops, with_values)
        c.showPage()
    c.save()
    return pages


def rasterize_pages(pdf: Path, dpi: int) -> list[Image.Image]:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(Path(tmp) / "p")], check=True, timeout=120)
        return [Image.open(p).convert("RGB") for p in sorted(Path(tmp).glob("p*.png"))]


def handwrite(page: Image.Image, ops: dict, dpi: int, rng: random.Random, font_path: str) -> Image.Image:
    """記入欄の値とチェックを、手書き風に重ねる。"""
    s = dpi / 72
    img = page.convert("RGBA")
    for t in ops["texts"]:
        if t["kind"] != "value" or not t["s"]:
            continue
        font = ImageFont.truetype(font_path, int(t["size"] * s * rng.uniform(1.12, 1.26)))
        box = font.getbbox(t["s"])
        tile = Image.new("RGBA", (box[2] + 12, box[3] + 12), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((6, 6), t["s"], font=font, fill=INK + (rng.randint(205, 245),))
        tile = tile.rotate(rng.uniform(-1.8, 1.8), resample=Image.Resampling.BICUBIC, expand=True)
        x = t["x"] * s - (tile.width if t["align"] == "right" else 0) + rng.uniform(-4, 5)
        y = (H - t["y"]) * s - tile.height * 0.78 + rng.uniform(-3, 3)
        img.alpha_composite(tile, (max(int(x), 0), max(int(y), 0)))
    draw = ImageDraw.Draw(img)
    for ck in ops["checks"]:
        if ck["on"]:  # レ点
            x, y = ck["x"] * s + rng.uniform(-2, 2), (H - ck["y"] - 10) * s + rng.uniform(-2, 2)
            u = 10 * s
            draw.line([(x + 0.05 * u, y + 0.45 * u), (x + 0.4 * u, y + 0.95 * u), (x + 1.25 * u, y - 0.3 * u)],
                      fill=INK + (235,), width=max(int(1.1 * s), 2), joint="curve")
    return img.convert("RGB")


def build_case(case: dict, font_path: str) -> Path:
    app, fmt = case["app"], case["format"]
    stem = f"{case['id']}_{app['type']}"
    rng = random.Random(int(case["id"][1:]) + 100)
    if fmt == "pdf2":
        out = FILES / f"{stem}.pdf"
        build_pdf(app, out, with_values=True)
        return out
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "form.pdf"
        handwritten = fmt.startswith("hw")
        dpi = 150 if fmt != "hw-photo" else 130
        pages = build_pdf(app, src, with_values=not handwritten)
        images = rasterize_pages(src, dpi)
        if handwritten:
            images = [handwrite(img, ops, dpi, rng, font_path) for img, ops in zip(images, pages)]
        if fmt == "hw-photo":
            out = FILES / f"{stem}.jpg"
            photo_like(images[0], rng).save(out, "JPEG", quality=74)
        else:
            out = FILES / f"{stem}.pdf"
            scans = [scan_like(img, rng) for img in images]
            scans[0].save(out, "PDF", resolution=dpi, save_all=True, append_images=scans[1:])
    return out


def main() -> None:
    FILES.mkdir(parents=True, exist_ok=True)
    for old in FILES.iterdir():
        old.unlink()
    font_path = klee_path()
    cases = json.loads((SAMPLES / "cases.src.json").read_text(encoding="utf-8"))
    result = []
    for case in cases:
        out = build_case(case, font_path)
        expected = check(case["app"], RULES_V2)
        result.append({"id": case["id"], "file": out.name, "format": case["format"], "app": case["app"], "expected": expected})
        print(f"{out.name}  {[f['rule'] for f in expected]}")
    (SAMPLES / "cases.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for p in build_kitei_dir(KITEI / "v2"):
        print(p.relative_to(ROOT))


if __name__ == "__main__":
    main()
