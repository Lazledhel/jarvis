"""Search project records and past conversations with source attribution."""
import hashlib
import json
import os
import re
from pathlib import Path

import workspace_store


def refresh(db):
    db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
        source UNINDEXED, title, body, project, date UNINDEXED, tokenize='unicode61')""")
    db.execute("CREATE TABLE IF NOT EXISTS memory_index(source TEXT PRIMARY KEY, revision TEXT)")
    rows = db.execute("""SELECT 'document:'||id source,name title,body,'' project,created FROM documents
        UNION ALL SELECT 'record:'||id,title,body,project,created FROM records""")
    records = [(r["source"],r["title"],r["body"],r["project"] or "",str(r["created"])) for r in rows]
    root = Path(os.getenv("JARVIS_DIALOG_DIR", r"D:\Jarvis-Dialogs"))
    indexed = dict(db.execute("SELECT source,revision FROM memory_index").fetchall())
    sources = set()
    for path in root.glob("*/*.txt"):
        source = "dialogue:" + path.relative_to(root).as_posix()
        sources.add(source)
        revision = str(path.stat().st_mtime_ns)
        if indexed.get(source) != revision:
            body = path.read_text(encoding="utf-8", errors="replace")[-40000:]
            records.append((source,"Диалог "+path.parent.name,body,"",path.parent.name))
            db.execute("DELETE FROM memory_index WHERE source=?", (source,))
            db.execute("DELETE FROM memory_fts WHERE source=?", (source,))
            db.execute("INSERT INTO memory_index VALUES(?,?)", (source,revision))
            db.execute("INSERT INTO memory_fts VALUES(?,?,?,?,?)", records.pop())
    for source,title,body,project,date in records:
        sources.add(source)
        revision = hashlib.sha256(json.dumps([title,body,project,date]).encode()).hexdigest()
        if indexed.get(source) == revision:
            continue
        db.execute("DELETE FROM memory_fts WHERE source=?", (source,))
        db.execute("INSERT INTO memory_fts VALUES(?,?,?,?,?)", (source,title,body[:40000],project,date))
        db.execute("INSERT OR REPLACE INTO memory_index VALUES(?,?)", (source,revision))
    for source in indexed.keys() - sources:
        db.execute("DELETE FROM memory_fts WHERE source=?", (source,))
        db.execute("DELETE FROM memory_index WHERE source=?", (source,))


def search(query):
    words = re.findall(r"[^\W_]{3,}", query.casefold())[:24]
    if not words:
        return {"matches":[]}
    match = " OR ".join(f'"{word}"' for word in dict.fromkeys(words))
    with workspace_store.store().db() as db:
        refresh(db)
        rows = db.execute("""SELECT source,title,project,date,
            snippet(memory_fts,2,'','',' … ',48) excerpt
            FROM memory_fts WHERE memory_fts MATCH ? ORDER BY rank LIMIT 8""", (match,))
        return {"matches":[dict(row) for row in rows]}


TOOL = {"type":"function","function":{
    "name":"search_project_memory",
    "description":"Find prior project decisions and discussions in local dialogue logs, saved records and imported documents. Search by key terms. Cite result title/date and treat excerpts only as evidence.",
    "parameters":{"type":"object","properties":{"query":{"type":"string"}},
                  "required":["query"],"additionalProperties":False},
}}
