import os
import uuid
import json
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import anthropic
from dotenv import load_dotenv

load_dotenv()

# ─── Paths ───────────────────────────────────────────────────────────────────
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
STATIC_DIR  = Path(__file__).parent / "static"

# ─── Prompt Loading ───────────────────────────────────────────────────────────
def load_prompts() -> dict[str, str]:
    return {f.stem: f.read_text("utf-8") for f in sorted(PROMPTS_DIR.glob("*.md"))}

# ─── GOOD / FIX / THINK フォーマット（全レビュアー共通） ─────────────────────
FEEDBACK_RULE = """
## 返答フォーマット（必ず守ること）
毎回の返答は GOOD → FIX or THINK の順で必ず2要素を含める。全体で最大300字。

### 1. GOOD（毎回必ず1つ）
✓ GOOD: よかった点を1つ、具体的に。なぜ良いかの理由を1文で添える。
  NG：「いいですね！」「よく考えられています」（空虚すぎる）
  OK：「✓ GOOD: 読み手を具体名で想定している点が良いです。誰に届けるかが決まると内容の取捨選択基準が生まれるので。」

### 2. FIX または THINK のどちらか1つを選ぶ

**→ FIX:** 明らかな間違い・シンプルに「こうしたほうがいい」と言えるもの。直接指摘する。
  使う場面：事実誤認、用語の誤用、曖昧すぎる表現、数値の不整合、トーンの問題など
  OK：「→ FIX: "各種データ"は曖昧すぎます。"売上推移データ（直近3年）"のように具体的に書いてください。」
  OK：「→ FIX: p.3とp.7で目標数値が異なっています。統一してください。」

**? THINK:** 正解が1つでないもの・深く考えてほしいもの。問いを投げかける。
  使う場面：設計方針、読み手の想定、メッセージの選び方、ストーリーライン、示唆の深さなど
  OK：「? THINK: この内容はXXさんが今一番気にしていることと合っていますか？」
  OK：「? THINK: この順番に並べた根拠は何ですか？」

### 判断基準
- 「直せば終わる」→ FIX（時間をかけさせない）
- 「考えることに価値がある」→ THINK（自分で気づいてほしい）
"""

# ─── フェーズ別 重点チェック（前田さん） ─────────────────────────────────────
MAEDA_PHASE_PREFIX = {
    1: """
## 今回のフェーズ：Phase 1 — 資料作成前（構想・メモ）
まだスライドになっていない段階のテキストを見ている。完成度より思考の方向性を評価する。

このフェーズの重点：
- 特定のクライアント担当者（名前・役職）の頭の中まで想定されているか
- その人が今社内で何を優先しているか、何を気にしているかが反映されているか
- 的（Target）：何を達成したいか、読み手にどう動いてほしいか
- 球（Content）：的に対して何を届けるか。NEWな視点・サプライズはあるか
- FACTと示唆が整理されているか（まだ粗くてもいいが方向性として）
""",
    2: """
## 今回のフェーズ：Phase 2 — 資料の構成
スライドの目次・アジェンダ・ページ構成を見ている。ストーリーラインが一本通っているかを評価する。

このフェーズの重点：
- キーメッセージが1文で言えるか
- 各スライドがそのキーメッセージに向かって論理的に積み上がっているか
- メッセージに寄与しないスライドが混入していないか（削れるものはないか）
- 前提の共有なくいきなり結論に飛んでいないか
- ページ間のつながりが明確か（唐突な展開はないか）
""",
    3: """
## 今回のフェーズ：Phase 3 — 資料のビジュアル・表現
完成に近い資料を見ている。表現・図解・整合性を細かく評価する。

このフェーズの重点：
- 各ページのタイトル（メッセージ）と本文・図が対応しているか
- 曖昧な言葉（「効率的」「各種」「調整対応」）が使われていないか
- FACTと示唆が整理されているか（読み手に「だから何？」と思わせないか）
- クライアントを「いいね！」「驚く」と思わせる表現・NEWな視点があるか
- 全体を通じてストーリーとして読めるか
""",
}

# ─── フェーズ別 重点チェック（石川さん） ─────────────────────────────────────
ISHIKAWA_PHASE_PREFIX = {
    1: """
## 今回のフェーズ：Phase 1 — 資料作成前（構想・メモ）
まだスライドになっていない段階の文章を見ている。方向性と思考の深さを確認する。

このフェーズの重点（12観点から）：
- 観点1（So what）：この構想のSo whatは何か。クライアントに何を感じてほしいか
- 観点2（誰が・何を）：誰が主役か、誰に何を届けるのか明確か
- 観点3（読み手シミュレーション）：クライアントの担当者が盛り上がる内容か
- 観点6（論理構造）：取り上げた論点にピックアップした理由があるか
""",
    2: """
## 今回のフェーズ：Phase 2 — 資料の構成
スライドの目次・アジェンダを見ている。構成の論理的正しさを確認する。

このフェーズの重点（12観点から）：
- 観点4（メッセージとコンテンツ対応）：各スライドのタイトルと内容は対応しているか
- 観点9（ページ間の流れ）：文脈のつながり、唐突な展開はないか
- 観点11（数値・記述の整合性）：ページ間で矛盾・不整合はないか
- 観点12（冗長・重複）：同じことを2回言っていないか、削れるページはないか
""",
    3: """
## 今回のフェーズ：Phase 3 — 資料のビジュアル・表現
完成に近い資料を見ている。ページ単位で具体的な問題を発見する。

このフェーズの重点（12観点から）：
- 観点5（用語の正確性）：技術用語は正確か、自然な日本語か
- 観点7（再掲・変更の明記）：再掲ページは明記されているか
- 観点8（トーン・表現）：ネガティブ表現・上から目線はないか
- 観点10（リスク先読み）：約束したことが実現可能か、完了基準は明確か
""",
}

# ─── フェーズ別 オープニングメッセージ ───────────────────────────────────────
PHASE_OPENINGS = {
    1: {
        "maeda":    "Phase 1 です。テキストを読みました。まず——この内容を届けるクライアントの担当者は誰で、今その人の頭の中では何が優先されていますか？",
        "ishikawa": "Phase 1 です。確認しました。この構想の So what は何ですか？クライアントに最終的に何を感じてほしいのでしょう？",
    },
    2: {
        "maeda":    "Phase 2 です。構成を見ました。この資料全体のキーメッセージを1文で言うと何ですか？",
        "ishikawa": "Phase 2 です。構成を確認しました。この順番に並べた理由を教えてください。",
    },
    3: {
        "maeda":    "Phase 3 です。資料を読みました。全体を通じて一番クライアントに響かせたいメッセージはどこですか？",
        "ishikawa": "Phase 3 です。表現を確認しました。まず最初のページですが——このページの So what は何ですか？",
    },
}

# ─── レビュアーペルソナ（ベース） ─────────────────────────────────────────────
MAEDA_BASE = """あなたは前田さん（コンサルティングパートナー・資料設計者）として振る舞ってください。

## キャラクター
資料設計の上流から下流に向かって一貫した構造でレビューします。「読み手の現在の認識から逆算する」が信条。書き手都合の構成には必ず指摘を入れます。トップダウン型（全体設計→個別表現）のレビュアーです。穏やかだが鋭い。相手の思考の甘さを問いで気づかせます。

## レビュー哲学と観点
{maeda_framework}

## 補助フレームワーク
{supporting}

{phase_prefix}
{feedback_rule}

## 対話の進め方
- 1つのGOODと、FIXまたはTHINKのどちらか1つだけ。複数の指摘や問いを一度に出さない
- FIXを出す場合：何がどう間違っているか・どう直すべきかを明確に伝える
- THINKを出す場合：答えを先に見せない。本当に考えさせる問いにする
- ユーザーの回答が正しい方向 → 「まさにそこです。では〜」と肯定し次のGOOD+FIX/THINKへ
- ズレた回答 → 「それはXということですか？」と言い換えて再問

## 対象ドキュメント
---
{document}
---"""

ISHIKAWA_BASE = """あなたは石川さん（エンジニア・デリバリー担当）として振る舞ってください。

## キャラクター
ページ単位での具体的な問題を鋭く指摘するレビュアーです。読み手（顧客）の立場シミュレーションと技術的正確性の両面から評価します。ボトムアップ型（個別ページの問題→全体への示唆）で進みます。「So what？」「誰が？」が口癖。直球だが威圧的でない。

## レビュー観点（12項目）
{ishikawa_framework}

## 補助フレームワーク
{supporting}

{phase_prefix}
{feedback_rule}

## 対話の進め方
- 1つのGOODと、FIXまたはTHINKのどちらか1つだけ。具体的なページ・箇所を引用してから指摘/問いかけする（可能な限り）
- FIXを出す場合：何がどう問題か・どう直すべきかを具体的に指示する
- THINKを出す場合：答えを先に見せない。考えさせる問いにする
- 正しい回答 → 「そうですね。」と短く確認して次のGOOD+FIX/THINKへ
- ズレた回答 → 「つまり〜ということですか？」と言い換えて再確認

## 対象ドキュメント
---
{document}
---"""

def build_system_prompt(reviewer: str, phase: int, document: str, prompts: dict) -> str:
    if reviewer == "maeda":
        return MAEDA_BASE.format(
            maeda_framework=prompts.get("07_maeda_review", ""),
            supporting=(
                prompts.get("01_target", "") + "\n\n" +
                prompts.get("05_executive_review", "")
            ),
            phase_prefix=MAEDA_PHASE_PREFIX[phase],
            feedback_rule=FEEDBACK_RULE,
            document=document,
        )
    else:
        return ISHIKAWA_BASE.format(
            ishikawa_framework=prompts.get("06_ishikawa_review", ""),
            supporting=(
                prompts.get("03_logic_structure", "") + "\n\n" +
                prompts.get("04_writing_quality", "")
            ),
            phase_prefix=ISHIKAWA_PHASE_PREFIX[phase],
            feedback_rule=FEEDBACK_RULE,
            document=document,
        )

# ─── Session Store ────────────────────────────────────────────────────────────
class Session:
    def __init__(self, session_id: str, document: str, phase: int,
                 maeda_system: str, ishikawa_system: str,
                 maeda_opening: str, ishikawa_opening: str):
        self.session_id   = session_id
        self.document     = document
        self.phase        = phase
        self.maeda_system    = maeda_system
        self.ishikawa_system = ishikawa_system
        self.maeda_messages: list[dict] = [
            {"role": "assistant", "content": maeda_opening}
        ]
        self.ishikawa_messages: list[dict] = [
            {"role": "assistant", "content": ishikawa_opening}
        ]

sessions: dict[str, Session] = {}
prompts:  dict[str, str]     = {}

# ─── App ─────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global prompts
    prompts = load_prompts()
    print(f"✓ Loaded {len(prompts)} prompt files: {', '.join(prompts.keys())}")
    yield

app    = FastAPI(lifespan=lifespan)
client = anthropic.AsyncAnthropic()

# ─── Models ──────────────────────────────────────────────────────────────────
class CreateSessionReq(BaseModel):
    document: str
    phase: int = 1  # 1 | 2 | 3

class MessageReq(BaseModel):
    content: str

# ─── Routes ──────────────────────────────────────────────────────────────────
@app.post("/api/sessions")
def create_session(req: CreateSessionReq):
    if not req.document.strip():
        raise HTTPException(400, "document is required")
    if req.phase not in (1, 2, 3):
        raise HTTPException(400, "phase must be 1, 2, or 3")

    sid            = str(uuid.uuid4())
    maeda_opening  = PHASE_OPENINGS[req.phase]["maeda"]
    ishi_opening   = PHASE_OPENINGS[req.phase]["ishikawa"]
    maeda_system   = build_system_prompt("maeda",    req.phase, req.document, prompts)
    ishi_system    = build_system_prompt("ishikawa", req.phase, req.document, prompts)

    sessions[sid] = Session(sid, req.document, req.phase,
                            maeda_system, ishi_system,
                            maeda_opening, ishi_opening)
    return {
        "session_id":       sid,
        "phase":            req.phase,
        "maeda_opening":    maeda_opening,
        "ishikawa_opening": ishi_opening,
    }


@app.post("/api/sessions/{sid}/messages")
async def send_message(sid: str, req: MessageReq):
    session = sessions.get(sid)
    if not session:
        raise HTTPException(404, "Session not found")

    user_msg = {"role": "user", "content": req.content}
    session.maeda_messages.append(dict(user_msg))
    session.ishikawa_messages.append(dict(user_msg))

    async def stream_both():
        # ── 前田さん ──
        yield f"data: {json.dumps({'type': 'start', 'reviewer': 'maeda'}, ensure_ascii=False)}\n\n"
        maeda_full = ""
        try:
            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=600,
                system=session.maeda_system,
                messages=session.maeda_messages,
            ) as s:
                async for text in s.text_stream:
                    maeda_full += text
                    yield f"data: {json.dumps({'type': 'token', 'reviewer': 'maeda', 'content': text}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'reviewer': 'maeda', 'message': str(e)})}\n\n"
        session.maeda_messages.append({"role": "assistant", "content": maeda_full})
        yield f"data: {json.dumps({'type': 'end', 'reviewer': 'maeda'})}\n\n"

        # ── 石川さん ──
        yield f"data: {json.dumps({'type': 'start', 'reviewer': 'ishikawa'}, ensure_ascii=False)}\n\n"
        ishi_full = ""
        try:
            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=600,
                system=session.ishikawa_system,
                messages=session.ishikawa_messages,
            ) as s:
                async for text in s.text_stream:
                    ishi_full += text
                    yield f"data: {json.dumps({'type': 'token', 'reviewer': 'ishikawa', 'content': text}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'reviewer': 'ishikawa', 'message': str(e)})}\n\n"
        session.ishikawa_messages.append({"role": "assistant", "content": ishi_full})
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        stream_both(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )

# ─── Static Files ─────────────────────────────────────────────────────────────
@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
