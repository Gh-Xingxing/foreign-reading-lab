# -*- coding: utf-8 -*-
"""Local full-stack app for intensive foreign-article reading.

The project intentionally uses only the Python standard library so it can run
on a fresh workstation without dependency installation.
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import sqlite3
import sys
import textwrap
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = BASE_DIR / "public"
MIGRATIONS_DIR = BASE_DIR / "migrations"
DEFAULT_DB_PATH = BASE_DIR / "data" / "reading_lab.sqlite3"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_db_path() -> Path:
    return Path(os.environ.get("FOREIGN_READING_DB", str(DEFAULT_DB_PATH)))


def connect_db(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def database(db_path: Path | None = None):
    conn = connect_db(db_path)
    try:
        yield conn
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        row["version"]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = file.stem
        if version in applied:
            continue
        conn.executescript(file.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations(version) VALUES (?)",
            (version,),
        )
    conn.commit()


def compact_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def split_paragraphs(text: str) -> list[str]:
    normalized = compact_spaces(text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", normalized) if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [p.strip() for p in normalized.split("\n") if p.strip()]
    return paragraphs or [normalized]


def split_sentences(paragraph: str) -> list[str]:
    closers = set("\"'”’)]}")
    endings = set(".!?。！？")
    sentences: list[str] = []
    start = 0
    i = 0
    while i < len(paragraph):
        char = paragraph[i]
        if char in endings:
            end = i + 1
            while end < len(paragraph) and paragraph[end] in closers:
                end += 1
            next_char = paragraph[end : end + 1]
            if not next_char or next_char.isspace():
                chunk = paragraph[start:end].strip()
                if chunk:
                    sentences.append(chunk)
                start = end
                i = end
                continue
        i += 1
    rest = paragraph[start:].strip()
    if rest:
        sentences.append(rest)
    return sentences or [paragraph.strip()]


def paragraph_role(position: int, total: int) -> str:
    if total <= 1:
        return "全文主旨"
    if position == 1:
        return "引入与问题设置"
    if position == total:
        return "收束与启发"
    if position == 2:
        return "背景与转折"
    if position == total - 1:
        return "论证推进"
    return "细节展开"


def create_article(conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
    title = str(payload.get("title") or "").strip()
    full_text = str(payload.get("content") or payload.get("full_text") or "").strip()
    if not title:
        raise ValueError("Title is required.")
    if len(full_text) < 80:
        raise ValueError("Article content should be at least 80 characters.")

    source = str(payload.get("source") or "").strip()
    url = str(payload.get("url") or "").strip()
    author = str(payload.get("author") or "").strip()
    published_at = str(payload.get("published_at") or "").strip()
    difficulty = str(payload.get("difficulty") or "B2-C1").strip()
    summary = str(payload.get("summary") or "").strip()

    cursor = conn.execute(
        """
        INSERT INTO articles(title, source, url, author, published_at, difficulty, full_text, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (title, source, url, author, published_at, difficulty, full_text, summary),
    )
    article_id = int(cursor.lastrowid)
    paragraphs = split_paragraphs(full_text)
    for p_index, paragraph in enumerate(paragraphs, start=1):
        p_cursor = conn.execute(
            "INSERT INTO paragraphs(article_id, position, text, role) VALUES (?, ?, ?, ?)",
            (article_id, p_index, paragraph, paragraph_role(p_index, len(paragraphs))),
        )
        paragraph_id = int(p_cursor.lastrowid)
        for s_index, sentence in enumerate(split_sentences(paragraph), start=1):
            conn.execute(
                """
                INSERT INTO sentences(article_id, paragraph_id, position, text)
                VALUES (?, ?, ?, ?)
                """,
                (article_id, paragraph_id, s_index, sentence),
            )
    conn.commit()
    return article_id


DEMO_ARTICLE = """When the first flood maps arrived in Northbridge, they looked less like warnings than accusations. Blocks that had been marketed as quiet, tree-lined streets were suddenly colored in layers of blue, and residents who had never thought of themselves as living near water discovered that water had been thinking about them for years.

The city could have answered with the usual performance of certainty: taller walls, thicker reports, another ribbon-cutting beside a pump station. Instead, the planning office began with listening sessions in laundromats, school cafeterias, and a bus depot where drivers knew which intersections failed before any sensor did. What emerged was not a single grand plan but a pattern of small truths, each one attached to a place and a person.

Those truths changed the grammar of the project. Engineers still modeled rainfall, but the models were read beside stories from night-shift nurses, shopkeepers, and teenagers who walked younger siblings home. A drainage ditch became a question about safe routes. A park renovation became a question about shade, insurance, and whether elderly residents would have somewhere dry to sit after a storm.

By the second year, the city had built fewer monuments than its campaign posters had promised. Yet it had repaired the culverts that mattered, moved two bus stops out of a flood pocket, trained neighborhood volunteers, and published a plain-language dashboard that made each delay visible. Trust did not rise because officials sounded more confident; it rose because residents could see what had been heard.

Northbridge is not a miracle story, and that is precisely why it is useful. Climate adaptation often arrives dressed as heroic engineering, but the work that lasts is usually more modest and more social. A city becomes resilient not when it conquers uncertainty, but when it learns to notice trouble early, share evidence honestly, and keep listening after the meeting ends."""


def seed_demo_data(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS total FROM articles").fetchone()["total"]
    if existing:
        return
    article_id = create_article(
        conn,
        {
            "title": "The City That Learned to Listen",
            "source": "Demo Atlantic-style Feature",
            "author": "Fictional sample for local demo",
            "published_at": "2026-09-18",
            "difficulty": "C1",
            "summary": "一篇关于城市气候适应、公共信任与社区倾听的外刊风格示例文章。",
            "content": DEMO_ARTICLE,
        },
    )
    sentences = conn.execute(
        "SELECT id, text FROM sentences WHERE article_id = ? ORDER BY paragraph_id, position",
        (article_id,),
    ).fetchall()
    first_sentence = sentences[0]
    last_sentence = sentences[-1]
    conn.execute(
        """
        INSERT INTO highlights(article_id, sentence_id, text, note, color)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            article_id,
            first_sentence["id"],
            first_sentence["text"],
            "开头用 flood maps 与 accusations 的比喻建立紧张感。",
            "amber",
        ),
    )
    conn.execute(
        """
        INSERT INTO vocabulary(article_id, term, pronunciation, definition_cn, translation_cn, example_sentence, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            article_id,
            "resilient",
            "/rɪˈzɪliənt/",
            "能恢复的；有韧性的；在压力下仍能调整并继续运转的。",
            "有韧性的",
            last_sentence["text"],
            "reviewing",
        ),
    )
    conn.execute(
        """
        INSERT INTO sentence_patterns(article_id, sentence_id, pattern, explanation, example, tags)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            article_id,
            last_sentence["id"],
            "not when..., but when...",
            "用否定预期再给出真正标准，适合写作中修正读者的直觉判断。",
            last_sentence["text"],
            "contrast,argument",
        ),
    )
    conn.execute(
        """
        INSERT INTO notes(article_id, title, body, tags)
        VALUES (?, ?, ?, ?)
        """,
        (
            article_id,
            "主旨笔记",
            "文章不是赞美单一工程方案，而是强调公共治理中的倾听、证据公开和持续反馈。",
            "主旨,赏析",
        ),
    )
    conn.commit()


def initialize_database() -> None:
    with database() as conn:
        migrate(conn)
        seed_demo_data(conn)


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def list_articles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT a.*, COUNT(s.id) AS sentence_count
        FROM articles a
        LEFT JOIN sentences s ON s.article_id = a.id
        GROUP BY a.id
        ORDER BY a.updated_at DESC, a.id DESC
        """
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_article(conn: sqlite3.Connection, article_id: int) -> dict[str, Any]:
    article = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if not article:
        raise KeyError("Article not found.")
    paragraphs = []
    for paragraph in conn.execute(
        "SELECT * FROM paragraphs WHERE article_id = ? ORDER BY position",
        (article_id,),
    ).fetchall():
        sentences = [
            row_to_dict(row)
            for row in conn.execute(
                "SELECT * FROM sentences WHERE paragraph_id = ? ORDER BY position",
                (paragraph["id"],),
            ).fetchall()
        ]
        item = row_to_dict(paragraph)
        item["sentences"] = sentences
        paragraphs.append(item)

    def many(table: str) -> list[dict[str, Any]]:
        return [
            row_to_dict(row)
            for row in conn.execute(
                f"SELECT * FROM {table} WHERE article_id = ? ORDER BY created_at DESC, id DESC",
                (article_id,),
            ).fetchall()
        ]

    result = row_to_dict(article)
    result["paragraphs"] = paragraphs
    result["highlights"] = many("highlights")
    result["vocabulary"] = many("vocabulary")
    result["patterns"] = many("sentence_patterns")
    result["notes"] = many("notes")
    return result


GLOSSARY: dict[str, dict[str, str]] = {
    "resilient": {
        "pronunciation": "/rɪˈzɪliənt/",
        "definition_cn": "能从冲击中恢复并继续运转的；有韧性的。",
        "translation_cn": "有韧性的",
    },
    "adaptation": {
        "pronunciation": "/ˌædæpˈteɪʃn/",
        "definition_cn": "适应；为应对新环境或新风险所做的调整。",
        "translation_cn": "适应；调适",
    },
    "culvert": {
        "pronunciation": "/ˈkʌlvərt/",
        "definition_cn": "涵洞；让水从道路或铁路下方通过的排水结构。",
        "translation_cn": "涵洞",
    },
    "dashboard": {
        "pronunciation": "/ˈdæʃbɔːrd/",
        "definition_cn": "数据看板；集中展示状态、进度和指标的界面。",
        "translation_cn": "仪表盘；看板",
    },
    "accusation": {
        "pronunciation": "/ˌækjuˈzeɪʃn/",
        "definition_cn": "指控；这里用于比喻地图像是在揭示城市规划的亏欠。",
        "translation_cn": "指控；责难",
    },
    "modest": {
        "pronunciation": "/ˈmɑːdɪst/",
        "definition_cn": "不夸张的；有限但务实的；谦逊的。",
        "translation_cn": "朴素的；适度的",
    },
}


def clean_term(term: str) -> str:
    return re.sub(r"[^A-Za-z\- ]", "", term).strip().lower()


def online_chat(prompt: str, task: str) -> tuple[str | None, str]:
    mode = os.environ.get("FOREIGN_READING_AI_MODE", "mock").lower()
    api_key = os.environ.get("FOREIGN_READING_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if mode != "online" or not api_key:
        return None, "mock"

    base_url = os.environ.get("FOREIGN_READING_API_BASE", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("FOREIGN_READING_MODEL", "gpt-4o-mini")
    endpoint = base_url + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an English intensive-reading assistant. Reply in concise Chinese unless asked otherwise.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "foreign-reading-lab/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"].strip()
        return content, "online"
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as exc:
        return None, f"mock_after_online_error:{exc.__class__.__name__}"


def lookup_word(term: str, context: str = "") -> dict[str, Any]:
    normalized = clean_term(term).split(" ")[0] if clean_term(term) else term.strip()
    if not normalized:
        raise ValueError("请选择一个单词或短语。")
    prompt = (
        "请解释这个英文词或短语，返回中文释义、常见搭配、文中语境含义和一个例句：\n"
        f"词语：{term}\n语境：{context[:800]}"
    )
    online, source = online_chat(prompt, "lookup")
    if online:
        return {
            "term": term.strip(),
            "pronunciation": "",
            "definition_cn": online,
            "translation_cn": "",
            "example_sentence": context,
            "source": source,
        }
    entry = GLOSSARY.get(normalized, {})
    return {
        "term": term.strip(),
        "pronunciation": entry.get("pronunciation", ""),
        "definition_cn": entry.get(
            "definition_cn",
            "离线词库暂无精确条目。可先根据上下文判断词性、情感色彩和句中作用；配置 API Key 后会返回在线释义。",
        ),
        "translation_cn": entry.get("translation_cn", "语境义待确认"),
        "example_sentence": context,
        "source": source,
    }


def translate_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("请选择需要翻译的文本。")
    prompt = "请把下面英文译成自然中文，并补充一句翻译难点说明：\n" + text[:3000]
    online, source = online_chat(prompt, "translate")
    if online:
        return {"text": text, "translation_cn": online, "source": source}

    lower = text.lower()
    if "not when" in lower and "but when" in lower:
        meaning = "这句的核心不是“征服不确定性”，而是“及早发现问题、诚实共享证据，并在会议结束后继续倾听”。"
    elif "could have answered" in lower:
        meaning = "作者先写城市本可以采用常见的确定性姿态，再转向更谦逊的倾听方案。"
    elif "what emerged" in lower:
        meaning = "最后形成的不是宏大的单一计划，而是许多与具体地点和居民经验相连的小事实。"
    else:
        meaning = "这是离线演示译意：先抓主语和谓语，再看转折、递进或因果关系；配置 API Key 后可返回完整机器翻译。"
    return {
        "text": text,
        "translation_cn": meaning,
        "source": source,
    }


def analyze_sentence(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("请选择一个句子。")
    prompt = "请用中文拆解下面英文句子的句型、语法骨架、亮点表达和仿写方向：\n" + text[:2000]
    online, source = online_chat(prompt, "sentence-analysis")
    if online:
        return {
            "pattern": "在线句型分析",
            "explanation": online,
            "example": text,
            "tags": "online",
            "source": source,
        }
    lower = text.lower()
    pattern = "主干 + 修饰成分"
    tags = ["structure"]
    tips = ["先划出主语和谓语，再把介词短语、从句或插入解释移到旁边处理。"]
    if "not " in lower and " but " in lower:
        pattern = "not..., but..."
        tags.append("contrast")
        tips.append("用“不是 A，而是 B”修正读者预期，适合写观点句。")
    if ";" in text:
        pattern = "分号并列推进"
        tags.append("rhythm")
        tips.append("分号前后通常是两个完整判断，后半句解释或推进前半句。")
    if lower.startswith("when ") or " when " in lower:
        tags.append("adverbial")
        tips.append("when 从句提供时间或条件背景，主句承载作者真正判断。")
    if "which" in lower or "that" in lower:
        tags.append("clause")
        tips.append("关系从句负责补充限定，让抽象名词获得更具体的边界。")
    return {
        "pattern": pattern,
        "explanation": " ".join(tips),
        "example": text,
        "tags": ",".join(tags),
        "source": source,
    }


def article_plain_text(article: dict[str, Any]) -> str:
    return "\n\n".join(paragraph["text"] for paragraph in article["paragraphs"])


def build_mock_analysis(article: dict[str, Any]) -> dict[str, Any]:
    paragraphs = article["paragraphs"]
    first = paragraphs[0]["sentences"][0]["text"] if paragraphs else ""
    last_sentences = paragraphs[-1]["sentences"] if paragraphs else []
    last = last_sentences[-1]["text"] if last_sentences else ""
    structure = [
        {
            "paragraph": p["position"],
            "role": p["role"],
            "focus": p["sentences"][0]["text"][:140] + ("..." if len(p["sentences"][0]["text"]) > 140 else ""),
        }
        for p in paragraphs
    ]
    heading_options = [
        "Listening as climate infrastructure",
        "Why bigger walls were not enough",
        "From technical models to lived evidence",
        "Visible progress and public trust",
        "Resilience as a social habit",
    ]
    ielts_training = [
        {
            "type": "Matching Headings",
            "question": "为每一段选择最合适的小标题，并写出定位依据。",
            "items": [
                {
                    "paragraph": item["paragraph"],
                    "answer": heading_options[min(index, len(heading_options) - 1)],
                    "evidence": item["focus"],
                }
                for index, item in enumerate(structure)
            ],
        },
        {
            "type": "True / False / Not Given",
            "question": "The city gained trust mainly because officials sounded more confident.",
            "answer": "False",
            "evidence": "Trust did not rise because officials sounded more confident; it rose because residents could see what had been heard.",
        },
        {
            "type": "Summary Completion",
            "question": "Climate adaptation is presented less as heroic engineering and more as a ______ and ______ practice.",
            "answer": "modest; social",
            "evidence": "the work that lasts is usually more modest and more social",
        },
        {
            "type": "Multiple Choice",
            "question": "What is the writer's main purpose?",
            "options": [
                "To praise a single flood-control technology",
                "To argue that public listening strengthens climate adaptation",
                "To compare two rival political campaigns",
                "To explain how insurance pricing works",
            ],
            "answer": "To argue that public listening strengthens climate adaptation",
            "evidence": last,
        },
        {
            "type": "Evidence Hunt",
            "question": "找出一处体现“技术方案被人的日常经验重新定义”的证据句。",
            "answer": "A drainage ditch became a question about safe routes.",
            "evidence": "A drainage ditch became a question about safe routes. A park renovation became a question about shade, insurance...",
        },
    ]
    return {
        "source": "mock",
        "thesis": "文章借城市防洪改造讨论公共治理：真正可靠的适应力来自持续倾听、公开证据和把技术方案放回人的日常经验中。",
        "hook": first,
        "closing": last,
        "study_flow": [
            {"phase": "略读", "minutes": 3, "goal": "只看标题、首末段和每段首句，判断主题、态度和文章类型。"},
            {"phase": "精读", "minutes": 15, "goal": "逐句处理长难句、逻辑转折和同义替换，只查影响理解的词。"},
            {"phase": "复盘", "minutes": 5, "goal": "完成题型训练，整理错因、段落功能和可复用表达。"},
        ],
        "structure": structure,
        "appreciation": [
            "开头把 flood maps 写成 accusations，立刻让客观图纸带上伦理压力，制造外刊常见的叙事钩子。",
            "中段反复把工程名词转化为人的路线、座椅、保险和等待时间，让抽象政策落到生活细节。",
            "结尾使用 not when..., but when... 的对照句式，把文章从案例提升到可迁移的观点。",
        ],
        "intensive_training": [
            {
                "type": "句子精读",
                "prompt": "找出第二段中 usual performance of certainty 指代的治理姿态，并解释作者为何要先写它。",
            },
            {
                "type": "表达仿写",
                "prompt": "用 not when..., but when... 仿写一句关于学习或工作的观点句。",
            },
            {
                "type": "逻辑标注",
                "prompt": "把全文标成“问题出现-方法转向-细节论证-结果呈现-观点升华”五段结构。",
            },
        ],
        "skimming_training": [
            "30 秒内读每段首句，判断本文是灾害新闻、城市治理评论，还是人物特写。",
            "圈出所有表示转折或修正预期的表达，如 instead, yet, not...but。",
            "只看最后一段，写出作者希望读者带走的一句话。",
        ],
        "ielts_training": ielts_training,
        "note_template": [
            "段落功能：P1 / P2 / P3 / P4 / P5 分别承担什么作用？",
            "关键词与同义替换：题干词、原文替换、干扰项各是什么？",
            "证据句：哪一句可以直接支持答案？",
            "错因：定位失败、同义替换未识别、主旨误判还是推断过度？",
            "输出句：用本文一个句型写 1 句自己的观点。",
        ],
    }


def get_analysis(conn: sqlite3.Connection, article_id: int, refresh: bool = False) -> dict[str, Any]:
    if not refresh:
        cached = conn.execute(
            "SELECT payload_json FROM analysis_cache WHERE article_id = ?",
            (article_id,),
        ).fetchone()
        if cached:
            article = get_article(conn, article_id)
            return ensure_analysis_shape(json.loads(cached["payload_json"]), article)
    article = get_article(conn, article_id)
    prompt = (
        "请基于全文和段落结构输出 JSON，字段包括 thesis, structure, appreciation, "
        "study_flow, intensive_training, skimming_training, ielts_training, note_template。文章如下：\n"
        + article_plain_text(article)[:8000]
    )
    online, source = online_chat(prompt, "analysis")
    if online:
        try:
            payload = json.loads(online)
            if isinstance(payload, dict):
                payload["source"] = source
            else:
                raise ValueError
        except ValueError:
            payload = build_mock_analysis(article)
            payload["online_raw"] = online
            payload["source"] = source
    else:
        payload = build_mock_analysis(article)
        payload["source"] = source
    payload = ensure_analysis_shape(payload, article)
    conn.execute(
        """
        INSERT INTO analysis_cache(article_id, payload_json, generated_by, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(article_id) DO UPDATE SET
          payload_json = excluded.payload_json,
          generated_by = excluded.generated_by,
          updated_at = CURRENT_TIMESTAMP
        """,
        (article_id, json.dumps(payload, ensure_ascii=False), payload.get("source", "mock")),
    )
    conn.commit()
    return payload


def ensure_analysis_shape(payload: dict[str, Any], article: dict[str, Any]) -> dict[str, Any]:
    fallback = build_mock_analysis(article)
    for key in ("study_flow", "ielts_training", "note_template"):
        if key not in payload or not payload[key]:
            payload[key] = fallback[key]
    return payload


def insert_row(conn: sqlite3.Connection, table: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed: dict[str, set[str]] = {
        "highlights": {"article_id", "sentence_id", "text", "note", "color"},
        "vocabulary": {
            "article_id",
            "term",
            "pronunciation",
            "definition_cn",
            "translation_cn",
            "example_sentence",
            "status",
        },
        "sentence_patterns": {
            "article_id",
            "sentence_id",
            "pattern",
            "explanation",
            "example",
            "tags",
        },
        "notes": {"article_id", "title", "body", "tags"},
    }
    if table not in allowed:
        raise ValueError("Unsupported table.")
    data = {key: payload[key] for key in allowed[table] if key in payload}
    if table == "notes":
        data.setdefault("title", "未命名笔记")
        data.setdefault("body", "")
    if table == "highlights":
        data.setdefault("color", "amber")
    if table == "vocabulary":
        data.setdefault("status", "new")
    if not data:
        raise ValueError("No data to save.")
    columns = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    cursor = conn.execute(
        f"INSERT INTO {table}({columns}) VALUES ({placeholders})",
        tuple(data.values()),
    )
    conn.commit()
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return row_to_dict(row)


def update_vocabulary_status(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    vocab_id = int(payload.get("id") or 0)
    status = str(payload.get("status") or "").strip()
    allowed = {"new", "reviewing", "mastered"}
    if not vocab_id or status not in allowed:
        raise ValueError("Vocabulary id and valid status are required.")
    conn.execute(
        "UPDATE vocabulary SET status = ? WHERE id = ?",
        (status, vocab_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM vocabulary WHERE id = ?", (vocab_id,)).fetchone()
    if not row:
        raise KeyError("Vocabulary item not found.")
    return row_to_dict(row)


def save_progress(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    article_id = int(payload["article_id"])
    current_sentence_id = payload.get("current_sentence_id")
    mode = str(payload.get("mode") or "intensive")
    existing = conn.execute(
        "SELECT id FROM reading_sessions WHERE article_id = ? ORDER BY id DESC LIMIT 1",
        (article_id,),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE reading_sessions
            SET current_sentence_id = ?, mode = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (current_sentence_id, mode, existing["id"]),
        )
        session_id = existing["id"]
    else:
        cursor = conn.execute(
            """
            INSERT INTO reading_sessions(article_id, current_sentence_id, mode)
            VALUES (?, ?, ?)
            """,
            (article_id, current_sentence_id, mode),
        )
        session_id = cursor.lastrowid
    conn.commit()
    return row_to_dict(
        conn.execute("SELECT * FROM reading_sessions WHERE id = ?", (session_id,)).fetchone()
    )


def export_markdown(conn: sqlite3.Connection, article_id: int) -> str:
    article = get_article(conn, article_id)
    analysis = get_analysis(conn, article_id)
    lines = [
        f"# {article['title']}",
        "",
        f"- Source: {article['source'] or 'Local import'}",
        f"- Author: {article['author'] or 'Unknown'}",
        f"- Published: {article['published_at'] or 'Unknown'}",
        f"- Difficulty: {article['difficulty']}",
        "",
        "## 原文",
        "",
    ]
    for paragraph in article["paragraphs"]:
        lines.append(paragraph["text"])
        lines.append("")
    lines.extend(["## 全文赏析", "", f"**主旨**：{analysis.get('thesis', '')}", ""])
    for item in analysis.get("appreciation", []):
        lines.append(f"- {item}")
    lines.extend(["", "## 段落结构", ""])
    for item in analysis.get("structure", []):
        lines.append(f"- P{item.get('paragraph')}: {item.get('role')} - {item.get('focus')}")
    lines.extend(["", "## 雅思训练流程", ""])
    for item in analysis.get("study_flow", []):
        lines.append(f"- {item.get('phase')}（{item.get('minutes')} 分钟）：{item.get('goal')}")
    lines.extend(["", "## 雅思题型训练", ""])
    for item in analysis.get("ielts_training", []):
        lines.append(f"### {item.get('type')}")
        lines.append(str(item.get("question", "")))
        if item.get("options"):
            for option in item["options"]:
                lines.append(f"- {option}")
        if item.get("items"):
            for sub_item in item["items"]:
                lines.append(
                    f"- P{sub_item.get('paragraph')}: {sub_item.get('answer')}  "
                    f"Evidence: {sub_item.get('evidence')}"
                )
        if item.get("answer"):
            lines.append(f"Answer: {item.get('answer')}")
        if item.get("evidence"):
            lines.append(f"Evidence: {item.get('evidence')}")
        lines.append("")
    lines.extend(["", "## 高亮", ""])
    if article["highlights"]:
        for item in article["highlights"]:
            lines.append(f"- {item['text']}  ")
            if item["note"]:
                lines.append(f"  Note: {item['note']}")
    else:
        lines.append("- 暂无高亮")
    lines.extend(["", "## 单词积累", ""])
    if article["vocabulary"]:
        for item in article["vocabulary"]:
            lines.append(f"- **{item['term']}** {item['pronunciation']} - {item['translation_cn']}")
            if item["definition_cn"]:
                lines.append(f"  - {item['definition_cn']}")
    else:
        lines.append("- 暂无单词")
    lines.extend(["", "## 重点句型", ""])
    if article["patterns"]:
        for item in article["patterns"]:
            lines.append(f"- **{item['pattern']}**：{item['explanation']}")
            if item["example"]:
                lines.append(f"  - {item['example']}")
    else:
        lines.append("- 暂无句型")
    lines.extend(["", "## 笔记", ""])
    if article["notes"]:
        for item in article["notes"]:
            lines.append(f"### {item['title']}")
            lines.append(item["body"])
            lines.append("")
    else:
        lines.append("- 暂无笔记")
    return "\n".join(lines).strip() + "\n"


def display_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W", "A"} else 1
    return width


def wrap_mixed_text(text: str, width: int = 68) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines() or [""]:
        if not raw:
            lines.append("")
            continue
        current = ""
        for token in re.split(r"(\s+)", raw):
            if not token:
                continue
            candidate = current + token
            if current and display_width(candidate) > width:
                lines.append(current.rstrip())
                current = token.lstrip()
            else:
                current = candidate
        if current:
            while display_width(current) > width:
                cut = 0
                seen = 0
                for idx, char in enumerate(current):
                    seen += 2 if unicodedata.east_asian_width(char) in {"F", "W", "A"} else 1
                    if seen >= width:
                        cut = idx + 1
                        break
                lines.append(current[:cut])
                current = current[cut:]
            if current:
                lines.append(current.rstrip())
    return lines


def pdf_hex(text: str) -> str:
    return text.encode("utf-16-be", errors="replace").hex().upper()


def build_pdf(title: str, markdown: str) -> bytes:
    body_lines = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            body_lines.extend(["", line[2:].strip(), ""])
        elif line.startswith("## "):
            body_lines.extend(["", line[3:].strip()])
        elif line.startswith("### "):
            body_lines.extend(["", line[4:].strip()])
        else:
            body_lines.append(re.sub(r"[*_`>#-]", "", line).strip())

    wrapped: list[str] = [title, ""]
    for line in body_lines:
        wrapped.extend(wrap_mixed_text(line, 72))

    page_height = 842
    top = 790
    left = 48
    line_height = 16
    lines_per_page = 45
    pages = [wrapped[i : i + lines_per_page] for i in range(0, len(wrapped), lines_per_page)]
    objects: list[bytes] = []

    def add(obj: str | bytes) -> int:
        objects.append(obj.encode("utf-8") if isinstance(obj, str) else obj)
        return len(objects)

    catalog_id = add("<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add(b"")
    font_id = add(b"")
    descendant_id = add(b"")
    descriptor_id = add(
        "<< /Type /FontDescriptor /FontName /STSong-Light /Flags 4 "
        "/FontBBox [0 -200 1000 900] /ItalicAngle 0 /Ascent 880 "
        "/Descent -120 /CapHeight 700 /StemV 80 >>"
    )
    objects[font_id - 1] = (
        f"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
        f"/Encoding /UniGB-UCS2-H /DescendantFonts [{descendant_id} 0 R] >>"
    ).encode("utf-8")
    objects[descendant_id - 1] = (
        f"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
        f"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 2 >> "
        f"/FontDescriptor {descriptor_id} 0 R /DW 1000 >>"
    ).encode("utf-8")
    page_ids: list[int] = []
    content_ids: list[int] = []
    for page_lines in pages:
        commands = [f"BT /F1 11 Tf {left} {top} Td {line_height} TL"]
        for line in page_lines:
            commands.append(f"<{pdf_hex(line)}> Tj T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("ascii")
        content_id = add(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
        content_ids.append(content_id)
        page_id = add(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 {page_height}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        page_ids.append(page_id)
    assert catalog_id == 1 and pages_id == 2 and font_id and descendant_id and descriptor_id
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("utf-8")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{idx} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_pos = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode(
            "ascii"
        )
    )
    return bytes(output)


def export_pdf(conn: sqlite3.Connection, article_id: int) -> bytes:
    article = get_article(conn, article_id)
    markdown = export_markdown(conn, article_id)
    return build_pdf(article["title"], markdown)


def safe_filename(name: str, suffix: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]+", "-", name).strip("-")
    return (cleaned or "article") + suffix


@dataclass
class ApiResponse:
    status: int
    body: bytes
    headers: dict[str, str]


def json_response(data: Any, status: int = 200) -> ApiResponse:
    return ApiResponse(
        status=status,
        body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


def bytes_response(body: bytes, content_type: str, filename: str | None = None) -> ApiResponse:
    headers = {"Content-Type": content_type}
    if filename:
        quoted = urllib.parse.quote(filename)
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quoted}"
    return ApiResponse(status=200, body=body, headers=headers)


def handle_get(path: str, query: dict[str, list[str]]) -> ApiResponse:
    with database() as conn:
        if path == "/api/health":
            return json_response(
                {
                    "ok": True,
                    "time": now_iso(),
                    "db": str(get_db_path()),
                    "mode": os.environ.get("FOREIGN_READING_AI_MODE", "mock"),
                }
            )
        if path == "/api/config":
            has_key = bool(os.environ.get("FOREIGN_READING_API_KEY") or os.environ.get("OPENAI_API_KEY"))
            return json_response(
                {
                    "ai_mode": "online" if os.environ.get("FOREIGN_READING_AI_MODE") == "online" and has_key else "mock",
                    "online_ready": has_key,
                    "tts": "browser" if not os.environ.get("FOREIGN_READING_TTS_ENDPOINT") else "configured",
                    "features": [
                        "import",
                        "reader",
                        "lookup",
                        "translate",
                        "tts",
                        "ielts-training",
                        "review-status",
                        "notes",
                        "markdown",
                        "pdf",
                    ],
                }
            )
        if path == "/api/articles":
            return json_response({"articles": list_articles(conn)})

        article_match = re.fullmatch(r"/api/articles/(\d+)(?:/(analysis|export))?", path)
        if article_match:
            article_id = int(article_match.group(1))
            action = article_match.group(2)
            if action == "analysis":
                refresh = query.get("refresh", ["0"])[0] == "1"
                return json_response(get_analysis(conn, article_id, refresh=refresh))
            if action == "export":
                fmt = query.get("format", ["markdown"])[0].lower()
                article = get_article(conn, article_id)
                if fmt == "pdf":
                    return bytes_response(
                        export_pdf(conn, article_id),
                        "application/pdf",
                        safe_filename(article["title"], ".pdf"),
                    )
                return bytes_response(
                    export_markdown(conn, article_id).encode("utf-8"),
                    "text/markdown; charset=utf-8",
                    safe_filename(article["title"], ".md"),
                )
            return json_response(get_article(conn, article_id))
    return json_response({"error": "Not found."}, status=404)


def handle_post(path: str, payload: dict[str, Any]) -> ApiResponse:
    with database() as conn:
        if path == "/api/articles":
            article_id = create_article(conn, payload)
            return json_response({"article": get_article(conn, article_id)}, status=201)
        if path == "/api/highlights":
            return json_response({"highlight": insert_row(conn, "highlights", payload)}, status=201)
        if path == "/api/vocabulary":
            return json_response({"vocabulary": insert_row(conn, "vocabulary", payload)}, status=201)
        if path == "/api/vocabulary/status":
            return json_response({"vocabulary": update_vocabulary_status(conn, payload)})
        if path == "/api/patterns":
            return json_response({"pattern": insert_row(conn, "sentence_patterns", payload)}, status=201)
        if path == "/api/notes":
            return json_response({"note": insert_row(conn, "notes", payload)}, status=201)
        if path == "/api/reading-progress":
            return json_response({"session": save_progress(conn, payload)}, status=201)
        if path == "/api/tools/lookup":
            return json_response({"result": lookup_word(str(payload.get("term") or ""), str(payload.get("context") or ""))})
        if path == "/api/tools/translate":
            return json_response({"result": translate_text(str(payload.get("text") or ""))})
        if path == "/api/tools/sentence-analysis":
            return json_response({"result": analyze_sentence(str(payload.get("text") or ""))})
        if path == "/api/tools/tts":
            text = str(payload.get("text") or "").strip()
            if not text:
                raise ValueError("No text to read.")
            return json_response(
                {
                    "result": {
                        "mode": "browser",
                        "message": "离线演示使用浏览器 Web Speech 朗读；配置在线 TTS 端点后可在此接口扩展音频生成。",
                        "text": text,
                    }
                }
            )
    return json_response({"error": "Not found."}, status=404)


class ReadingLabHandler(BaseHTTPRequestHandler):
    server_version = "ForeignReadingLab/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    def send_api_response(self, response: ApiResponse) -> None:
        self.send_response(response.status)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response.body)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_api_response(json_response({"error": message}, status=status))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            try:
                response = handle_get(path, urllib.parse.parse_qs(parsed.query))
                self.send_api_response(response)
            except KeyError as exc:
                self.send_error_json(404, str(exc))
            except Exception as exc:  # noqa: BLE001 - top-level request guard
                self.send_error_json(500, str(exc))
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_error_json(404, "Not found.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
            response = handle_post(parsed.path, payload)
            self.send_api_response(response)
        except json.JSONDecodeError:
            self.send_error_json(400, "Invalid JSON.")
        except (ValueError, sqlite3.IntegrityError) as exc:
            self.send_error_json(400, str(exc))
        except KeyError as exc:
            self.send_error_json(404, str(exc))
        except Exception as exc:  # noqa: BLE001 - top-level request guard
            self.send_error_json(500, str(exc))

    def serve_static(self, path: str) -> None:
        requested = "index.html" if path in {"", "/"} else path.lstrip("/")
        candidate = (PUBLIC_DIR / requested).resolve()
        if PUBLIC_DIR.resolve() not in candidate.parents and candidate != PUBLIC_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.exists() or not candidate.is_file():
            candidate = PUBLIC_DIR / "index.html"
        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix in {".html", ".css", ".js", ".svg"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def run(host: str, port: int) -> None:
    initialize_database()
    server = ThreadingHTTPServer((host, port), ReadingLabHandler)
    print(f"Foreign Reading Lab running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Foreign Reading Lab.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5178")))
    parser.add_argument("--init-db", action="store_true", help="Run migrations and seed data, then exit.")
    args = parser.parse_args(argv)
    if args.init_db:
        initialize_database()
        print(f"Database ready: {get_db_path()}")
        return
    run(args.host, args.port)


if __name__ == "__main__":
    main()

