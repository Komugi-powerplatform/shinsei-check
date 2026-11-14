"""サンプルの申請書ファイルと、ナレッジ用の規程 PDF を作る。

    .venv/bin/python -m shinsei.generate

samples/cases.src.json（真値＋仕込んだ不備）を読み、次を書き出す。
- samples/files/NN_種別.pdf|jpg : 申請書（文字つき PDF／スキャン風 PDF／写真風 JPG）
- samples/cases.json            : 真値＋判定エンジンが出した期待される指摘
- kitei/pdf/*.pdf               : 規程の PDF
"""

import json
import random
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from shinsei.rules import check

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
FILES = SAMPLES / "files"
KITEI = ROOT / "kitei"
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT = "ArialUnicode"
COMPANY = "株式会社サンプル商会"
TITLES = {"keihi": "経費精算申請書", "shucchou": "出張申請書", "ringi": "稟議書"}

pdfmetrics.registerFont(TTFont(FONT, FONT_PATH))

BODY = ParagraphStyle("body", fontName=FONT, fontSize=10.5, leading=17)
CELL = ParagraphStyle("cell", fontName=FONT, fontSize=10.5, leading=15)
TITLE = ParagraphStyle("title", fontName=FONT, fontSize=18, leading=26, alignment=1)
H2 = ParagraphStyle("h2", fontName=FONT, fontSize=12, leading=20, spaceBefore=8)
RIGHT = ParagraphStyle("right", fontName=FONT, fontSize=10.5, leading=15, alignment=2)
GRID = [
    ("FONTNAME", (0, 0), (-1, -1), FONT),
    ("FONTSIZE", (0, 0), (-1, -1), 10.5),
    ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
]
LABEL_BG = colors.Color(0.92, 0.92, 0.92)


def jp_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.year}年{d.month}月{d.day}日"


def yen(n: int) -> str:
    return f"{n:,} 円"


def header_rows(app: dict) -> list[tuple[str, str]]:
    """種別ごとの記入欄。空欄の不備はそのまま空で出す。"""
    rows = [
        ("申請日", jp_date(app["apply_date"])),
        ("所属", app["department"]),
        ("申請者", app["applicant"]),
    ]
    if app["type"] == "keihi":
        rows += [
            ("支払日", jp_date(app["pay_date"])),
            ("目的", app["purpose"]),
            (
                "参加人数（会議費のみ）",
                f"{app['participants']} 名" if app["participants"] else "",
            ),
        ]
    elif app["type"] == "shucchou":
        rows += [
            ("出張先", app["destination"]),
            ("出発日", jp_date(app["depart_date"])),
            ("帰着日", jp_date(app["return_date"])),
            ("宿泊数", f"{app['nights']} 泊"),
            ("目的", app["purpose"]),
        ]
    else:
        rows += [("件名", app["subject"]), ("目的", app["purpose"])]
    return rows


def attachment_line(app: dict) -> str | None:
    """添付書類のチェック欄。出張申請書には欄が無い。"""
    names = {"keihi": ["領収書"], "ringi": ["見積書"]}.get(app["type"])
    if not names:
        return None
    return "　".join(("■ " if n in app["attachments"] else "□ ") + n for n in names)


def build_form(app: dict, out: Path) -> None:
    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    width = A4[0] - 44 * mm
    story = [
        Paragraph(COMPANY, RIGHT),
        Spacer(1, 4 * mm),
        Paragraph(TITLES[app["type"]], TITLE),
        Spacer(1, 6 * mm),
    ]

    head = Table(
        [[k, Paragraph(v, CELL)] for k, v in header_rows(app)],
        colWidths=[48 * mm, width - 48 * mm],
        style=TableStyle(GRID + [("BACKGROUND", (0, 0), (0, -1), LABEL_BG)]),
    )
    story += [head, Spacer(1, 6 * mm), Paragraph("明細", H2)]

    items = [["品名", "費目", "金額"]] + [
        [Paragraph(i["name"], CELL), i["category"], yen(i["amount"])]
        for i in app["items"]
    ]
    story.append(
        Table(
            items,
            colWidths=[width - 78 * mm, 38 * mm, 40 * mm],
            style=TableStyle(
                GRID
                + [
                    ("BACKGROUND", (0, 0), (-1, 0), LABEL_BG),
                    ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ]
            ),
        )
    )
    story.append(Spacer(1, 6 * mm))

    foot = [["申請金額（税込）", yen(app["amount"])]]
    line = attachment_line(app)
    if line:
        foot.append(["添付書類", line])
    foot.append(["決裁者", f"{app['approver_position']}　{app['approver_name']}"])
    story.append(
        Table(
            foot,
            colWidths=[48 * mm, width - 48 * mm],
            style=TableStyle(GRID + [("BACKGROUND", (0, 0), (0, -1), LABEL_BG)]),
        )
    )
    doc.build(story)


# --- スキャン風・写真風 ---


def rasterize(pdf: Path, dpi: int) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "page"
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", "-singlefile", str(pdf), str(base)],
            check=True,
            timeout=60,
        )
        return Image.open(f"{base}.png").convert("RGB")


def add_noise(img: Image.Image, sigma: float, amount: float) -> Image.Image:
    noise = Image.effect_noise(img.size, sigma).convert(img.mode)
    return Image.blend(img, noise, amount)


def scan_like(page: Image.Image, rng: random.Random) -> Image.Image:
    """複合機で取り込んだような、少し傾いたグレースケールの画像。"""
    img = page.convert("L")
    img = img.rotate(
        rng.uniform(-1.6, 1.6), resample=Image.Resampling.BICUBIC, fillcolor=255
    )
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    img = add_noise(img, 28, 0.10)
    return ImageEnhance.Contrast(img).enhance(1.25)


def photo_like(page: Image.Image, rng: random.Random) -> Image.Image:
    """机に置いた紙をスマホで斜めから撮ったような画像。"""
    w, h = page.size
    pad = int(w * 0.12)
    desk = Image.new("RGB", (w + pad * 2, h + pad * 2), (96, 78, 60))
    desk = add_noise(desk, 18, 0.25)
    paper = page.rotate(
        rng.uniform(-4, 4),
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor=(96, 78, 60),
    )
    desk.paste(
        paper, ((desk.width - paper.width) // 2, (desk.height - paper.height) // 2)
    )

    # 元画像の四隅を少しずらして読むことで、遠近のゆがみを付ける
    dw, dh = desk.size
    k = int(dw * 0.05)
    quad = (-k, 0, k, dh, dw - k, dh, dw + k, 0)  # 左上・左下・右下・右上
    img = desk.transform(
        desk.size,
        Image.Transform.QUAD,
        quad,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(96, 78, 60),
    )

    # 片側が暗くなる照明むら
    shade = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(shade)
    for x in range(dw):
        draw.line([(x, 0), (x, dh)], fill=int(70 * x / dw))
    img = Image.composite(Image.new("RGB", img.size, (30, 26, 22)), img, shade)
    img = img.filter(ImageFilter.GaussianBlur(0.9))
    return add_noise(img, 14, 0.06)


def build_case(case: dict) -> Path:
    app = case["app"]
    stem = f"{case['id']}_{app['type']}"
    rng = random.Random(int(case["id"]))
    if case["format"] == "pdf":
        out = FILES / f"{stem}.pdf"
        build_form(app, out)
        return out
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "form.pdf"
        build_form(app, src)
        if case["format"] == "scan":
            out = FILES / f"{stem}.pdf"
            scan_like(rasterize(src, 150), rng).save(out, "PDF", resolution=150)
        else:
            out = FILES / f"{stem}.jpg"
            photo_like(rasterize(src, 130), rng).save(out, "JPEG", quality=72)
    return out


# --- 規程 PDF ---


def md_to_story(text: str) -> list:
    """規程で使っている記法（# 見出し・段落・番号リスト・表）だけを PDF に組む。"""
    story, table = [], []

    def flush_table():
        if table:
            rows = [r for r in table if not re.fullmatch(r"[\s|\-]+", r)]
            data = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            story.append(
                Table(
                    data,
                    colWidths=[70 * mm, 40 * mm],
                    style=TableStyle(
                        GRID + [("BACKGROUND", (0, 0), (-1, 0), LABEL_BG)]
                    ),
                )
            )
            story.append(Spacer(1, 3 * mm))
            table.clear()

    for line in text.splitlines():
        if line.startswith("|"):
            table.append(line)
            continue
        flush_table()
        if line.startswith("# "):
            story += [Paragraph(line[2:], TITLE), Spacer(1, 4 * mm)]
        elif line.startswith("## "):
            story.append(Paragraph(line[3:], H2))
        elif line.strip():
            story.append(Paragraph(line, BODY))
    flush_table()
    return story


def build_kitei() -> list[Path]:
    return build_kitei_dir(KITEI)


def build_kitei_dir(src_dir: Path) -> list[Path]:
    """src_dir の規程（*.md）を src_dir/pdf/ に PDF で出す。"""
    out_dir = src_dir / "pdf"
    out_dir.mkdir(exist_ok=True)
    outs = []
    for md in sorted(src_dir.glob("*.md")):
        out = out_dir / f"{md.stem}.pdf"
        SimpleDocTemplate(
            str(out),
            pagesize=A4,
            leftMargin=25 * mm,
            rightMargin=25 * mm,
            topMargin=22 * mm,
            bottomMargin=22 * mm,
        ).build(md_to_story(md.read_text(encoding="utf-8")))
        outs.append(out)
    return outs


def main() -> None:
    FILES.mkdir(parents=True, exist_ok=True)
    for old in FILES.iterdir():
        old.unlink()
    cases = json.loads((SAMPLES / "cases.src.json").read_text(encoding="utf-8"))
    result = []
    for case in cases:
        out = build_case(case)
        result.append(
            {
                "id": case["id"],
                "file": out.name,
                "format": case["format"],
                "app": case["app"],
                "expected": check(case["app"]),
            }
        )
        print(f"{out.name}  {[f['rule'] for f in result[-1]['expected']]}")
    (SAMPLES / "cases.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for p in build_kitei():
        print(p.relative_to(ROOT))


if __name__ == "__main__":
    main()
