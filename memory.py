import json
import math
import re
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None

from config import GEMINI_API_KEY


class LongTermMemory:
    """Persistent vector memory backed by SQLite.

    Gemini embeddings are used when available. A deterministic local hashed
    embedding is used as a fallback so memory remains usable offline / during
    API capacity errors.
    """

    def __init__(self, db_path=None):
        base = Path.home() / ".ultron"
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else base / "memory.db"
        self.client = genai.Client(api_key=GEMINI_API_KEY) if (GEMINI_API_KEY and genai is not None) else None
        self.embedding_model = "gemini-embedding-2"
        self.dim = 768
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            con.commit()

    @staticmethod
    def _normalize(v):
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def _local_embedding(self, text):
        # Stable signed hashing vector: lightweight semantic-ish fallback with
        # no extra package/model download. Gemini embeddings remain primary.
        vec = [0.0] * self.dim
        tokens = re.findall(r"[a-z0-9']+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        return self._normalize(vec)

    @staticmethod
    def _extract_embedding(result):
        # google-genai has used both singular and plural result shapes.
        if getattr(result, "embeddings", None):
            emb = result.embeddings[0]
            values = getattr(emb, "values", None)
            if values is not None:
                return list(values)
        emb = getattr(result, "embedding", None)
        if emb is not None and getattr(emb, "values", None) is not None:
            return list(emb.values)
        raise RuntimeError("Embedding response did not contain vector values")

    def _embed(self, text, query=False):
        if self.client:
            try:
                task = "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"
                result = self.client.models.embed_content(
                    model=self.embedding_model,
                    contents=text,
                    config=types.EmbedContentConfig(
                        task_type=task,
                        output_dimensionality=self.dim,
                    ),
                )
                return self._normalize(self._extract_embedding(result)), "gemini"
            except Exception as e:
                print(f"MEMORY EMBEDDING FALLBACK> {type(e).__name__}: {e}")
        return self._local_embedding(text), "local"

    @staticmethod
    def _cosine(a, b):
        if len(a) != len(b):
            return -1.0
        return sum(x * y for x, y in zip(a, b))

    def add(self, text):
        text = str(text).strip()
        if not text:
            return False, "I need something to remember."
        vector, provider = self._embed(text, query=False)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute(
                "INSERT INTO memories(text, vector_json, provider, created_at) VALUES (?, ?, ?, ?)",
                (text, json.dumps(vector), provider, now),
            )
            con.commit()
        return True, f"I'll remember that {text}."

    def search(self, query, limit=4, min_score=0.18):
        query = str(query).strip()
        if not query:
            return []
        qvec, provider = self._embed(query, query=True)
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, text, vector_json, provider, created_at FROM memories"
            ).fetchall()

        scored = []
        for row in rows:
            try:
                vec = json.loads(row[2])
                # Gemini-query vs local-document vectors are not comparable.
                # If providers differ, compare using local embeddings instead.
                if row[3] != provider:
                    local_q = self._local_embedding(query)
                    local_doc = self._local_embedding(row[1])
                    score = self._cosine(local_q, local_doc)
                else:
                    score = self._cosine(qvec, vec)
                if score >= min_score:
                    scored.append({
                        "id": row[0], "text": row[1], "score": score,
                        "created_at": row[4],
                    })
            except Exception:
                continue
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def recent(self, limit=5):
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, text, created_at FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"id": r[0], "text": r[1], "created_at": r[2]} for r in rows]

    def forget_matching(self, query):
        matches = self.search(query, limit=1, min_score=0.12)
        if not matches:
            return False, "I couldn't find a matching memory to forget."
        match = matches[0]
        with self._connect() as con:
            con.execute("DELETE FROM memories WHERE id = ?", (match["id"],))
            con.commit()
        return True, f"I forgot that {match['text']}."

    def clear(self):
        with self._connect() as con:
            count = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            con.execute("DELETE FROM memories")
            con.commit()
        return True, f"Long-term memory cleared. I removed {count} memories."

    def count(self):
        with self._connect() as con:
            return con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def context_for(self, query, limit=4):
        matches = self.search(query, limit=limit)
        if not matches:
            return ""
        return "\n".join(f"- {m['text']}" for m in matches)
