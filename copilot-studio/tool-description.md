# Shinsei Check ツール（フロー）の説明文

Copilot Studio のツール説明に貼る文。生成オーケストレーターはこの説明を見てツールを選ぶ。

---

添付された申請書（経費精算申請書・出張申請書・稟議書の PDF または画像）を読み取り、社内規程のルール（金額上限、決裁者、申請期限、必須添付、記入漏れ、明細合計の不一致）で判定して、不備の一覧を条番号つきで返します。ユーザーが申請書のファイルを添付したとき、申請書の不備・チェック・確認を頼まれたときは、必ずこのツールを使ってください。入力は添付されたファイルです。

入力 file の設定（ツールの「入力」で式を指定する）:
- contentBytes: First(System.Activity.Attachments).Content
- name: First(System.Activity.Attachments).Name
