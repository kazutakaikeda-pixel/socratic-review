# Socratic Review

> 提案書・定例資料をAIがソクラテス式で問い返すレビューツール

前田さん（パートナー・資料設計者）と石川さん（エンジニア・デリバリー担当）の2人のレビュー観点を再現したAIが、
**答えを与えるのではなく、問いを投げかける**ことで、自ら考える力を育てます。

---

## デモ

資料を貼り付けると、2名から交互に問いかけが届きます。

```
前田さん: この資料を読んだ後、読み手にどう動いてもらいたいですか？

石川さん: 最初の内容を見て、このSo whatは何ですか？
         読み手にとって何が嬉しいのでしょう？
```

返答するとさらに深掘りされます。答えを「もらう」のではなく、「気づく」ことが目的です。

---

## 前田さんのレビュー観点（4層）

| 層 | 問い |
|---|---|
| **第1層** 読み手の認識 | 特定の担当者の頭の中まで想定しているか？NEWな視点はあるか？ |
| **第2層** FACT vs 示唆 | 事実の羅列で終わっていないか？「だから何？」の示唆があるか？ |
| **第3層** ストーリー | キーメッセージに向かって各スライドが積み上がっているか？ |
| **第4層** 表現 | 曖昧な言葉・内輪用語を使っていないか？ |

## 石川さんのレビュー観点（12項目）

So what・誰が何を・読み手シミュレーション・用語正確性・論理構造・再掲明記・トーン・ページ間の流れ・リスク先読み・数値整合・冗長削除

---

## セットアップ

**必要なもの**
- Python 3.10+
- Anthropic API キー（[取得はこちら](https://console.anthropic.com/)）

```bash
git clone https://github.com/YOUR_USERNAME/socratic-review.git
cd socratic-review/app

# 環境変数を設定
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 依存パッケージをインストール
pip3 install -r requirements.txt

# 起動
uvicorn main:app --reload --port 8000
```

ブラウザで `http://localhost:8000` を開いて使用できます。

---

## ファイル構成

```
├── prompts/                  # レビュー観点（Markdownで管理）
│   ├── 06_ishikawa_review.md # 石川さん視点（12観点）
│   └── 07_maeda_review.md    # 前田さん視点（4層構造）
├── app/
│   ├── main.py               # FastAPI バックエンド
│   └── static/               # フロントエンド（HTML/CSS/JS）
└── README.md
```

### レビュー観点の追加

`prompts/` に新しい `.md` ファイルを追加するだけで、次回起動時から自動反映されます。

---

## 技術スタック

- **Backend**: Python / FastAPI + Uvicorn
- **AI**: Claude API（claude-sonnet-4-6）via Anthropic SDK
- **Frontend**: Vanilla HTML / CSS / JavaScript（ビルドステップなし）
- **Streaming**: Server-Sent Events（SSE）

---

## なぜソクラテス式か

答えをもらうだけでは、次回同じ資料を作るときに同じ失敗をする。
問いを受けて自分で考えることで、レビュー観点が内面化される。
繰り返し使うことで、最終的にはレビュアーの工数が不要になることを目指しています。
