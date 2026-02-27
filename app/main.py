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

# ─── Paths ──────────────────────────────────────────────────────────────────
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
STATIC_DIR = Path(__file__).parent / "static"

# ─── Prompt Loading ──────────────────────────────────────────────────────────
def load_prompts() -> dict[str, str]:
    return {f.stem: f.read_text("utf-8") for f in sorted(PROMPTS_DIR.glob("*.md"))}

# ─── Reviewer Personas ───────────────────────────────────────────────────────
MAEDA_OPENING = "この資料を読みました。まず伺いたいのですが——この資料を読んだ後、読み手にどう動いてもらいたいですか？"
ISHIKAWA_OPENING = "資料を確認しました。まず一点——最初の内容を見て、このSo whatは何ですか？読み手にとって何が嬉しいのでしょう？"

MAEDA_PERSONA = """あなたは前田さん（コンサルティングパートナー・資料設計者）として振る舞ってください。

## キャラクター
資料設計の上流から下流に向かって一貫した構造でレビューします。「読み手の現在の認識から逆算する」が信条。書き手都合の構成には必ず指摘を入れます。トップダウン型（全体設計→個別表現）のレビュアーです。穏やかだが鋭い。相手の思考の甘さを問いで気づかせます。

## レビュー哲学と観点
{maeda_framework}

## 補助フレームワーク
{supporting}

## 対話ルール（必ず守ること）
1. **答えを直接与えない** ── 全返答の70%は問いかけ。30%は直接フィードバック可
2. **1ターンで聞くことは1つだけ** ── 複数の問いを一度に投げない
3. **必ず疑問文で締める** ── フィードバック後も問いで終わる
4. **最大150字** ── 短く鋭く
5. 敬語・丁寧語。親しみやすいトーン

## 対話の進め方
- 第1層（読み手の認識から逆算）→ 第2層（ストーリー）→ 第3層（表現）の順で進む
- 上の層が解決するまで下の層に進まない
- 正しい方向の回答 → 「まさにそこです。では〜」と肯定し次の問いへ
- ズレた回答 → 「それはXということですか？」と言い換えて再問
- 迷走が続く場合のみ → 「よくあるパターンとして〜がありますが」と一般論でヒント（答えは出さない）

## 対象ドキュメント
---
{document}
---"""

ISHIKAWA_PERSONA = """あなたは石川さん（エンジニア・デリバリー担当）として振る舞ってください。

## キャラクター
ページ単位での具体的な問題を鋭く指摘するレビュアーです。読み手（顧客）の立場シミュレーションと技術的正確性の両面から評価します。ボトムアップ型（個別ページの問題→全体への示唆）で進みます。「So what？」「誰が？」が口癖。直球だが威圧的でない。「確認する」スタンス。

## レビュー観点（12項目）
{ishikawa_framework}

## 補助フレームワーク
{supporting}

## 対話ルール（必ず守ること）
1. **答えを直接与えない** ── 全返答の70%は問いかけ。30%は直接フィードバック可
2. **1ターンで確認することは1観点の1論点だけ**
3. **必ず疑問文で締める**
4. **最大200字** ── 簡潔・明快
5. 具体的なページ・箇所を引用してから問いかける（可能な限り）
6. ですます調

## 対話の進め方
- 観点1（So what）から、またはドキュメントで最も問題のある観点から始める
- 1観点が合格したら次へ
- 正しい回答 → 「そうですね。」と短く確認して次の観点へ
- ズレた回答 → 「つまり〜ということですか？」と言い換えて再確認

## 対象ドキュメント
---
{document}
---"""

def build_system_prompt(reviewer: str, document: str, prompts: dict) -> str:
    if reviewer == "maeda":
        return MAEDA_PERSONA.format(
            maeda_framework=prompts.get("07_maeda_review", ""),
            supporting=(
                prompts.get("01_target", "") + "\n\n" +
                prompts.get("05_executive_review", "")
            ),
            document=document,
        )
    else:
        return ISHIKAWA_PERSONA.format(
            ishikawa_framework=prompts.get("06_ishikawa_review", ""),
            supporting=(
                prompts.get("03_logic_structure", "") + "\n\n" +
                prompts.get("04_writing_quality", "")
            ),
            document=document,
        )

# ─── Session Store ───────────────────────────────────────────────────────────
class Session:
    def __init__(self, session_id: str, document: str,
                 maeda_system: str, ishikawa_system: str):
        self.session_id = session_id
        self.document = document
        self.maeda_system = maeda_system
        self.ishikawa_system = ishikawa_system
        # Each reviewer has its own conversation history
        self.maeda_messages: list[dict] = [
            {"role": "assistant", "content": MAEDA_OPENING}
        ]
        self.ishikawa_messages: list[dict] = [
            {"role": "assistant", "content": ISHIKAWA_OPENING}
        ]

sessions: dict[str, Session] = {}
prompts: dict[str, str] = {}

# ─── FastAPI App ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global prompts
    prompts = load_prompts()
    print(f"✓ Loaded {len(prompts)} prompt files: {', '.join(prompts.keys())}")
    yield

app = FastAPI(lifespan=lifespan)
client = anthropic.AsyncAnthropic()

# ─── Pydantic Models ─────────────────────────────────────────────────────────
class CreateSessionReq(BaseModel):
    document: str

class MessageReq(BaseModel):
    content: str

# ─── API Routes ──────────────────────────────────────────────────────────────
@app.post("/api/sessions")
def create_session(req: CreateSessionReq):
    if not req.document.strip():
        raise HTTPException(400, "document is required")

    sid = str(uuid.uuid4())
    maeda_system = build_system_prompt("maeda", req.document, prompts)
    ishikawa_system = build_system_prompt("ishikawa", req.document, prompts)

    sessions[sid] = Session(sid, req.document, maeda_system, ishikawa_system)
    return {
        "session_id": sid,
        "maeda_opening": MAEDA_OPENING,
        "ishikawa_opening": ISHIKAWA_OPENING,
    }


@app.post("/api/sessions/{sid}/messages")
async def send_message(sid: str, req: MessageReq):
    session = sessions.get(sid)
    if not session:
        raise HTTPException(404, "Session not found")

    # Append user message to both histories
    user_msg = {"role": "user", "content": req.content}
    session.maeda_messages.append(dict(user_msg))
    session.ishikawa_messages.append(dict(user_msg))

    async def stream_both():
        # ── Maeda response ──
        yield f"data: {json.dumps({'type': 'start', 'reviewer': 'maeda'}, ensure_ascii=False)}\n\n"
        maeda_full = ""
        try:
            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=512,
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

        # ── Ishikawa response ──
        yield f"data: {json.dumps({'type': 'start', 'reviewer': 'ishikawa'}, ensure_ascii=False)}\n\n"
        ishikawa_full = ""
        try:
            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=512,
                system=session.ishikawa_system,
                messages=session.ishikawa_messages,
            ) as s:
                async for text in s.text_stream:
                    ishikawa_full += text
                    yield f"data: {json.dumps({'type': 'token', 'reviewer': 'ishikawa', 'content': text}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'reviewer': 'ishikawa', 'message': str(e)})}\n\n"

        session.ishikawa_messages.append({"role": "assistant", "content": ishikawa_full})
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
