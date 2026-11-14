"""v2 サンプル 20 件の元データ samples/v2/cases.src.json を書き出す。

    .venv/bin/python scripts/make_cases_v2.py

長い明細を手で打つと足し算を間違えるので、行の並びはここで組み、申請金額は合計から出す。
intended は「仕込んだ不備」の覚え書き（手で書く）。テストが判定エンジンの結果と突き合わせる。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def row(name, category, amount, note=""):
    return {"name": name, "category": category, "amount": amount, "note": note}


KEIHI_POOL = [
    row("地下鉄（本社〜東和商事 往復）", "交通費", 420), row("コピー用紙 A4 5 箱", "消耗品費", 3850),
    row("宅配便（見本品の発送）", "通信費", 1280), row("バス（倉庫〜駅）", "交通費", 230),
    row("付せん・クリップ", "消耗品費", 1640), row("書留（契約書 2 通）", "通信費", 1240),
    row("JR（本社〜川崎工場 往復）", "交通費", 640), row("書籍「販売実務の手引き」", "図書費", 2420),
    row("地下鉄（本社〜北斗物産 往復）", "交通費", 480), row("封筒 角 2 100 枚", "消耗品費", 990),
    row("レターパック 4 通", "通信費", 2400), row("私鉄（本社〜西部倉庫 往復）", "交通費", 760),
    row("ホワイトボード用マーカー", "消耗品費", 1320), row("バス（展示会場〜駅）", "交通費", 260),
    row("業界紙 11 月分", "図書費", 3300), row("宅配便（カタログの発送）", "通信費", 1860),
    row("地下鉄（本社〜商工会館 往復）", "交通費", 360), row("クリアホルダー 50 枚", "消耗品費", 1100),
    row("JR（本社〜大宮営業所 往復）", "交通費", 1140), row("速達郵便 3 通", "通信費", 1050),
    row("インデックスラベル", "消耗品費", 580), row("地下鉄（本社〜法務局 往復）", "交通費", 400),
]
TRIP_POOL = [
    row("在来線（支店〜工場 往復）", "交通費", 2340), row("地下鉄（駅〜支店 往復）", "交通費", 420),
    row("バス（駅〜工場）", "交通費", 380), row("在来線（空港〜市内）", "交通費", 520),
    row("地下鉄（市内移動 1 日目）", "交通費", 640), row("地下鉄（市内移動 2 日目）", "交通費", 580),
    row("バス（工場〜駅）", "交通費", 380), row("在来線（市内〜空港）", "交通費", 520),
    row("私鉄（支店〜取引先 往復）", "交通費", 860), row("地下鉄（市内移動 3 日目）", "交通費", 460),
    row("バス（ホテル〜支店 往復）", "交通費", 440), row("在来線（取引先 2 社の訪問）", "交通費", 1180),
    row("地下鉄（市内移動 4 日目）", "交通費", 500), row("バス（会場〜駅）", "交通費", 240),
]
EQUIP_POOL = [
    row("ノート PC（営業一課）", "備品", 148000), row("ノート PC（営業二課）", "備品", 148000),
    row("27 型モニター", "備品", 32000), row("ドッキングステーション", "備品", 18500),
    row("無線キーボード・マウス", "備品", 9800), row("Web 会議用カメラ", "備品", 12400),
    row("会議用スピーカーフォン", "備品", 38000), row("複合機用トナー一式", "備品", 46000),
    row("表計算ソフト 追加ライセンス", "ソフトウェア", 54000), row("ウイルス対策ソフト 年間更新", "ソフトウェア", 39600),
    row("無停電電源装置", "備品", 42000), row("ネットワークスイッチ", "備品", 27500),
    row("外付けハードディスク", "備品", 16800), row("シュレッダー", "備品", 58000),
    row("書類保管庫", "備品", 74000), row("設置・初期設定の作業費", "業務委託", 66000),
    row("ノート PC（総務課）", "備品", 148000), row("プロジェクター", "備品", 98000),
    row("スクリーン", "備品", 24000), row("電話会議システム 年間利用料", "ソフトウェア", 120000),
    row("デスクトップ PC（経理課）", "備品", 132000), row("バックアップ用 NAS", "備品", 86000),
]


def total(items):
    return sum(i["amount"] for i in items)


def base(type_, applicant, dept, klass, apply_date, items, purpose, approver, attachments, amount_off=0, **extra):
    return {
        "type": type_, "applicant": applicant, "department": dept, "applicant_class": klass, "apply_date": apply_date,
        "items": items, "amount": total(items) + amount_off, "purpose": purpose,
        "approver_name": approver[1], "approver_position": approver[0], "attachments": attachments, **extra,
    }


KACHO, BUCHO, YAKUIN = ("課長", "中村 浩"), ("部長", "渡辺 修"), ("役員", "松本 隆之")
CASES = []


def add(id_, fmt, intended, app):
    CASES.append({"id": id_, "format": fmt, "intended": intended, "app": app})


# --- 不備なし 4 件 ---
add("V01", "hw-scan", [], base(
    "keihi", "佐藤 健二", "営業一課", "一般", "2026-11-10",
    [row("取引先との会食（和食店）", "会議費", 31600)], "年間契約の更新について取引先 2 社と打合せ", KACHO, ["領収書"],
    pay_date="2026-11-06", participants=4, external_participants=True))
add("V02", "pdf2", [], base(
    "keihi", "伊藤 美咲", "総務課", "一般", "2026-11-12",
    KEIHI_POOL[:16] + [row("タクシー（本社〜倉庫）", "交通費", 5000), row("タクシー（駅〜商工会館）", "交通費", 7200, "大型の展示パネルを運ぶため")],
    "10 月分の立替経費の精算", KACHO, ["領収書"], pay_date="2026-10-30", participants=None, external_participants=None))
add("V03", "hw-scan", [], base(
    "shucchou", "木村 卓郎", "商品企画課", "管理職", "2026-11-02",
    [row("新幹線（東京〜名古屋 往復）", "交通費", 22000), row("ホテル 2 泊", "宿泊費", 36000)],
    "協力工場 2 社での試作品の確認", KACHO, [],
    destination="名古屋市", depart_date="2026-11-16", return_date="2026-11-18", nights=2))
add("V04", "scan2", [], base(
    "ringi", "高橋 誠", "情報システム課", "一般", "2026-11-05", EQUIP_POOL[:16],
    "本社 2 階の執務室の機器の入れ替え", YAKUIN, ["見積書"], subject="本社 2 階の機器の入れ替え", quotes_count=2))

# --- 不備 1 つ 8 件 ---
add("V05", "hw-scan", ["R1"], base(
    "shucchou", "鈴木 彩", "営業二課", "一般", "2026-11-04",
    [row("新幹線（東京〜新大阪 往復）", "交通費", 28000), row("ホテル 1 泊", "宿泊費", 14000)],
    "堺市の販売代理店との年間契約の更新交渉", KACHO, [],
    destination="大阪府堺市", depart_date="2026-11-17", return_date="2026-11-18", nights=1))
add("V06", "hw-scan", ["R1"], base(
    "shucchou", "吉田 大輔", "営業二課", "一般", "2026-11-05",
    [row("特急（往復）", "交通費", 6400), row("ホテル 2 泊", "宿泊費", 27000)],
    "八王子の物流拠点の立ち上げ支援", KACHO, [],
    destination="東京都八王子市", depart_date="2026-11-18", return_date="2026-11-20", nights=2))
add("V07", "hw-photo", ["R1"], base(
    "keihi", "加藤 翔", "営業一課", "一般", "2026-11-11",
    [row("取引先との会食（中華料理店）", "会議費", 41000)], "主要取引先との来期の取引条件の打合せ", KACHO, ["領収書"],
    pay_date="2026-11-09", participants=5, external_participants=True))
add("V08", "pdf2", ["R7"], base(
    "keihi", "清水 優", "総務課", "一般", "2026-11-13",
    KEIHI_POOL[2:20] + [row("タクシー（本社〜西部倉庫）", "交通費", 6400), row("タクシー（駅〜法務局）", "交通費", 1800)],
    "10 月後半から 11 月前半の立替経費の精算", KACHO, ["領収書"], pay_date="2026-10-28", participants=None, external_participants=None))
add("V09", "hw-scan", ["R8"], base(
    "ringi", "藤井 聡史", "情報システム課", "一般", "2026-11-10",
    [row("受発注管理ソフトウェア（年間ライセンス）", "ソフトウェア", 1170000), row("初期設定の作業費", "業務委託", 280000)],
    "手作業の受発注処理をなくし入力ミスを減らす", YAKUIN, ["見積書"], subject="受発注管理ソフトウェアの導入", quotes_count=1))
add("V10", "pdf2", ["R6"], base(
    "ringi", "橋本 哲也", "総務課", "一般", "2026-11-06", EQUIP_POOL[2:16] + EQUIP_POOL[17:19] + EQUIP_POOL[20:22],
    "支店 3 か所の事務機器の入れ替え", BUCHO, ["見積書"], amount_off=-3000, subject="支店の事務機器の入れ替え", quotes_count=1))
add("V11", "scan2", ["R3"], base(
    "shucchou", "小林 直子", "総務課", "管理職", "2026-11-11",
    [row("航空券（羽田〜福岡 往復）", "交通費", 42000), row("ホテル 4 泊", "宿泊費", 60000)] + TRIP_POOL,
    "九州支店の事務所移転の立ち会いと取引先への挨拶", BUCHO, [],
    destination="福岡市", depart_date="2026-11-16", return_date="2026-11-20", nights=4))
add("V12", "hw-scan", ["R1"], base(
    "keihi", "池田 茜", "営業一課", "一般", "2026-11-10",
    [row("課内の打合せ昼食（洋食店）", "会議費", 16500)], "来月の展示会の役割分担の打合せ", KACHO, ["領収書"],
    pay_date="2026-11-07", participants=3, external_participants=False))

# --- 不備 2〜4 つ 8 件 ---
add("V13", "pdf2", ["R1", "R7", "R7"], base(
    "shucchou", "前田 光", "営業一課", "一般", "2026-11-02",
    [row("新幹線（東京〜新大阪 往復）", "交通費", 28000), row("ホテル 3 泊", "宿泊費", 46500)] + TRIP_POOL[:12]
    + [row("タクシー（新大阪駅〜展示会場）", "交通費", 5800), row("タクシー（会場〜ホテル）", "交通費", 4200),
       row("タクシー（ホテル〜取引先）", "交通費", 9000), row("タクシー（取引先〜新大阪駅）", "交通費", 5600, "見本品の箱を運ぶため")],
    "大阪での展示会への出展と取引先 3 社の訪問", BUCHO, [],
    destination="大阪市", depart_date="2026-11-17", return_date="2026-11-20", nights=3))
add("V14", "hw-scan", ["R2", "R8"], base(
    "ringi", "山本 恵", "マーケティング課", "一般", "2026-11-09",
    [row("春の展示会 出展小間料", "広告", 760000), row("ブース施工費", "広告", 320000)],
    "新製品の認知拡大と販売店の新規開拓", BUCHO, ["見積書"], subject="春の文具展示会への出展", quotes_count=1))
add("V15", "scan2", ["R4", "R6", "R7"], base(
    "keihi", "阿部 圭", "営業二課", "一般", "2026-11-12",
    KEIHI_POOL[:20] + [row("タクシー（本社〜川崎工場）", "交通費", 12000)],
    "10 月分の立替経費の精算", KACHO, [], amount_off=-1200, pay_date="2026-10-31", participants=None, external_participants=None))
add("V16", "hw-photo", ["R1", "R3"], base(
    "shucchou", "石井 千秋", "マーケティング課", "管理職", "2026-11-13",
    [row("新幹線（新大阪〜東京 往復）", "交通費", 28000), row("ホテル 2 泊", "宿泊費", 37000)],
    "東京本社での来期の販促計画の会議", KACHO, [],
    destination="東京都港区", depart_date="2026-11-16", return_date="2026-11-18", nights=2))
add("V17", "pdf2", ["R2", "R4", "R5"], base(
    "ringi", "森 和也", "情報システム課", "一般", "2026-11-10", EQUIP_POOL[:15] + EQUIP_POOL[16:22] + [row("サーバー室の空調機", "備品", 940000)],
    "", BUCHO, [], subject="本社の機器の一括更新", quotes_count=0))
add("V18", "hw-scan", ["R3", "R5"], base(
    "keihi", "石川 舞", "商品企画課", "一般", "2026-11-12",
    [row("デザイン事務所との会食（洋食店）", "会議費", 24000)], "新シリーズのデザインの打合せ", KACHO, ["領収書"],
    pay_date="2026-10-03", participants=None, external_participants=True))
add("V19", "scan2", ["R2", "R6", "R7"], base(
    "shucchou", "佐々木 亮", "営業二課", "一般", "2026-11-04",
    [row("新幹線（東京〜名古屋 往復）", "交通費", 22000), row("ホテル 2 泊", "宿泊費", 30000), row("レンタカー 3 日間", "交通費", 39600)]
    + TRIP_POOL[:12] + [row("タクシー（名古屋駅〜取引先）", "交通費", 5200)],
    "名古屋地区の新規販売店 4 社との契約前の訪問", KACHO, [], amount_off=2000,
    destination="名古屋市", depart_date="2026-11-18", return_date="2026-11-20", nights=2))
add("V20", "pdf2", ["R6", "R8"], base(
    "ringi", "岡田 葵", "マーケティング課", "一般", "2026-11-11",
    EQUIP_POOL[4:16] + [row("展示用什器 一式", "備品", 337500), row("什器の運搬・設置費", "業務委託", 149000)] + [row("商品撮影 30 点", "業務委託", 39400)],
    "直営ショールームの開設準備", YAKUIN, ["見積書"], amount_off=-10000, subject="ショールームの開設準備", quotes_count=1))

out = ROOT / "samples" / "v2" / "cases.src.json"
out.write_text(json.dumps(CASES, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
for c in CASES:
    a = c["app"]
    print(c["id"], c["format"], a["type"], len(a["items"]), "行", f"{a['amount']:,}", c["intended"])
