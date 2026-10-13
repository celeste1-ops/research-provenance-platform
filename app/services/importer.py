"""Bringing earlier material in, and taking steps out as a table (DECISIONS D-060).

* A folder of Markdown notes (an Obsidian vault, or any folder of .md files): each note becomes a
  step, oldest first. Its date is the one in its front matter (``date:``/``created:``) or, if it
  has none, the file's own date — kept only as the author's claimed date, never as a verified
  time. ``[[links]]`` and links to other notes become "builds on" relations to the notes before
  it; pictures it shows are attached.
* A table (CSV, as Excel or Numbers save it): one step per row, with optional date, type, text,
  key-step mark and "builds on" (row numbers).
* Steps out as a table (CSV that Excel opens), for counting and sorting elsewhere. A table is not
  evidence: the evidence bundle is what can be checked.

Nothing here goes over the network; the files are read on this computer.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from app.config import MAX_UPLOAD_BYTES
from app.i18n import tr
from app.services.ledger import EntryInput, LedgerError, UploadedFile
from app.services.previews import IMAGE_TYPES
from provenance_core.records import NODE_TYPES

MAX_NOTES = 500
MAX_ROWS = 1000
NOTE_SUFFIXES = {".md", ".markdown"}
SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", "__pycache__"}
TITLE_LIMIT = 200
_FRONT = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_WIKI = re.compile(r"(!?)\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_MDLINK = re.compile(r"(!?)\[[^\]]*\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.M)
_DATE = re.compile(r"(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?")
DATE_KEYS = ("date", "created", "created_at", "creation_date", "日期", "创建时间", "创建日期")
TITLE_KEYS = ("title", "标题")


class ImportProblem(Exception):
    pass


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def parse_date(text: str) -> tuple[str, str] | None:
    """'2025-9-14', '2025/09', '2025' -> (claimed date, precision); None if it is not a date."""
    m = _DATE.match((text or "").strip())
    if not m:
        return None
    year, month, day = m.group(1), m.group(2), m.group(3)
    try:
        if day:
            return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d"), "day"
        if month:
            return datetime(int(year), int(month), 1).strftime("%Y-%m"), "month"
        return datetime(int(year), 1, 1).strftime("%Y"), "year"
    except ValueError:
        return None


def _claimed(date: tuple[str, str] | None) -> dict | None:
    """Only a date before today is older material; today's steps have their date stamp."""
    if date is None or date[0] >= _today()[: len(date[0])]:
        return None
    return {"claimed_date": date[0], "level": "L1"}


def _folder(path: str) -> Path:
    raw = (path or "").strip().strip('"')
    folder = Path(raw).expanduser() if raw else None
    if folder is None or not folder.is_absolute():
        raise ImportProblem("choose a full folder path")
    if not folder.is_dir():
        raise ImportProblem("that folder does not exist")
    return folder


# ---------------------------------------------------------------- notes


@dataclass
class Note:
    rel: str  # path inside the folder, with "/"
    title: str
    body: str  # without the front matter
    date: tuple[str, str] | None
    date_source: str  # "front matter" or "file date"
    links: list[str] = field(default_factory=list)  # other notes it links to
    images: list[str] = field(default_factory=list)  # pictures it shows


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    m = _FRONT.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not line.startswith((" ", "\t", "-")):
            meta[key.strip().lower()] = value.strip().strip("'\"")
    return meta, text[m.end():]


def scan_notes(folder: Path) -> list[Note]:
    files: list[Path] = []
    for path in sorted(folder.rglob("*")):
        parts = path.relative_to(folder).parts
        if any(p.startswith(".") or p in SKIP_DIRS for p in parts):
            continue
        if path.is_file():
            files.append(path)
    notes = [p for p in files if p.suffix.lower() in NOTE_SUFFIXES]
    if not notes:
        raise ImportProblem("there are no Markdown notes (.md) in that folder")
    if len(notes) > MAX_NOTES:
        raise ImportProblem(f"that folder holds more than {MAX_NOTES} notes; choose one of its subfolders")

    def rel(p: Path) -> str:
        return p.relative_to(folder).as_posix()

    by_name = {}
    for p in files:
        by_name.setdefault(p.name.lower(), rel(p))
    by_note = {}
    for p in notes:
        by_note.setdefault(p.stem.lower(), rel(p))
        by_note.setdefault(rel(p)[: -len(p.suffix)].lower(), rel(p))

    out = []
    for p in notes:
        meta, body = _front_matter(p.read_text(encoding="utf-8", errors="replace"))
        title = next((meta[k] for k in TITLE_KEYS if meta.get(k)), None)
        if not title:
            heading = _HEADING.search(body)
            title = heading.group(1) if heading else p.stem
        date, source = None, "file date"
        for k in DATE_KEYS:
            if meta.get(k) and parse_date(meta[k]):
                date, source = parse_date(meta[k]), "front matter"
                break
        if date is None:
            date = (datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d"), "day")
        note = Note(rel(p), title.strip()[:TITLE_LIMIT], body.strip(), date, source)
        for embed, target in _WIKI.findall(body):
            target = target.strip()
            if PurePosixPath(target).suffix.lower() in IMAGE_TYPES:
                found = by_name.get(PurePosixPath(target).name.lower())
                if found and embed:
                    note.images.append(found)
            else:
                found = by_note.get(target.lower()) or by_note.get(PurePosixPath(target).stem.lower())
                if found and found != note.rel:
                    note.links.append(found)
        for embed, url in _MDLINK.findall(body):
            if re.match(r"[a-z][a-z0-9+.-]*:", url, re.I) or url.startswith("#"):
                continue  # web addresses and anchors
            try:
                target = (p.parent / unquote(url.split("#")[0])).resolve()
                inside = target.relative_to(folder.resolve()).as_posix()
            except (ValueError, OSError):
                continue
            if target.suffix.lower() in IMAGE_TYPES and embed and target.is_file():
                note.images.append(inside)
            elif target.suffix.lower() in NOTE_SUFFIXES and inside != note.rel and target.is_file():
                note.links.append(inside)
        note.links = list(dict.fromkeys(note.links))
        note.images = list(dict.fromkeys(note.images))
        out.append(note)
    out.sort(key=lambda n: (n.date[0] if n.date else "9999", n.rel))
    return out


def inspect_notes(path: str) -> dict:
    folder = _folder(path)
    notes = scan_notes(folder)
    names = {n.rel for n in notes}
    return {
        "folder": str(folder), "name": folder.name, "count": len(notes),
        "dated": sum(1 for n in notes if n.date_source == "front matter"),
        "notes": [{"rel": n.rel, "title": n.title, "date": n.date[0] if n.date else None,
                   "date_source": n.date_source, "links": sum(1 for x in n.links if x in names),
                   "images": len(n.images)} for n in notes],
    }


def import_notes(ledger, path: str, project_id: str, selected: list[str] | None = None,
                 node_type: str = "note") -> dict:
    if project_id not in {p.id for p in ledger.projects()}:
        raise LedgerError("unknown project")
    if node_type not in NODE_TYPES:
        raise LedgerError("unknown step type")
    folder = _folder(path)
    notes = scan_notes(folder)
    if selected is not None:
        wanted = set(selected)
        notes = [n for n in notes if n.rel in wanted]
    ids: dict[str, str] = {}
    for n in notes:
        files, names = [], set()
        for img in n.images:
            source = folder / img
            name = PurePosixPath(img).name
            if name in names or not source.is_file() or source.stat().st_size > MAX_UPLOAD_BYTES:
                continue
            names.add(name)
            files.append(UploadedFile(name, source.read_bytes(), None))
        ids[n.rel] = ledger.create_entry(EntryInput(
            project_id=project_id, node_type=node_type, title=n.title or PurePosixPath(n.rel).stem,
            body=n.body or None, files=files,
            relations=[{"to": ids[x], "rel": "uses"} for x in n.links if x in ids],
            author_statement=tr("Imported from the notes folder {folder}: {file}", folder=folder.name, file=n.rel),
            import_info=_claimed(n.date),
        ))
    return {"imported": len(ids)}


# ---------------------------------------------------------------- tables

COLUMNS = {
    "date": ("date", "日期", "claimed date", "when", "时间"),
    "type": ("type", "kind", "类型", "种类"),
    "title": ("title", "标题", "name", "名称"),
    "text": ("text", "body", "notes", "content", "description", "内容", "正文", "说明", "描述"),
    "builds_on": ("builds on", "based on", "uses", "links", "基于", "用到", "来自", "依据"),
    "key": ("key step", "key", "milestone", "关键步骤", "关键"),
    # a table this app wrote numbers its steps (#12); "builds on" then names those numbers
    "number": ("step", "步骤编号", "no.", "#", "序号"),
}
TYPE_WORDS = {
    "idea": ("idea", "想法"),
    "claim": ("hypothesis", "claim", "hypothesis / claim", "假设", "论断", "假设 / 论断", "假设/论断"),
    "note": ("note", "notes", "笔记", "说明", "记录"),
    "experiment": ("experiment", "实验"),
    "code": ("code", "代码", "程序"),
    "dataset": ("data", "dataset", "数据"),
    "figure": ("figure", "plot", "图", "图表", "图片"),
    "document": ("document", "draft", "文档", "草稿"),
    "publication": ("paper", "publication", "preprint", "论文", "预印本", "文章"),
}
_YES = {"yes", "y", "true", "1", "x", "✓", "是", "对", "关键", "★"}


@dataclass
class Row:
    number: int  # 1 = the first row under the header
    title: str
    node_type: str
    text: str
    date: tuple[str, str] | None
    builds_on: list[int]
    key: bool
    problems: list[str] = field(default_factory=list)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):  # Excel on a Chinese Windows saves CSV as GBK
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportProblem("the table is not in a text encoding the app can read; save it as CSV UTF-8")


def parse_table(data: bytes) -> list[Row]:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise ImportProblem("the table is empty")
    header = [h.strip().lower() for h in rows[0]]
    where = {}
    for key, words in COLUMNS.items():
        for i, h in enumerate(header):
            if h in words and key not in where:
                where[key] = i
    if "title" not in where:
        raise ImportProblem("the table needs a column called title (标题)")
    if len(rows) - 1 > MAX_ROWS:
        raise ImportProblem(f"the table has more than {MAX_ROWS} rows; split it")

    def cell(r: list[str], key: str) -> str:
        i = where.get(key)
        return r[i].strip() if i is not None and i < len(r) else ""

    numbers = {}
    for n, r in enumerate(rows[1:], 1):
        mark = cell(r, "number").lstrip("#")
        if mark.isdigit():
            numbers.setdefault(int(mark), n)

    out = []
    for n, r in enumerate(rows[1:], 1):
        row = Row(n, cell(r, "title")[:TITLE_LIMIT], "note", cell(r, "text"), None, [],
                  cell(r, "key").lower() in _YES)
        if not row.title:
            row.problems.append(tr("no title: this row is left out"))
        kind = cell(r, "type").lower()
        if kind:
            match = next((t for t, words in TYPE_WORDS.items() if kind in words or kind == t), None)
            if match:
                row.node_type = match
            else:
                row.problems.append(tr("unknown type “{kind}”: recorded as a note", kind=kind))
        if cell(r, "date"):
            row.date = parse_date(cell(r, "date"))
            if row.date is None:
                row.problems.append(tr("this date could not be read: left out"))
        for part in re.split(r"[,;，；\s]+", cell(r, "builds_on").replace("#", " ")):
            if part.isdigit():
                ref = numbers.get(int(part), int(part)) if numbers else int(part)
                if 1 <= ref < n:
                    row.builds_on.append(ref)
                else:
                    row.problems.append(tr("builds on row {ref}, which is not an earlier row: left out", ref=ref))
        out.append(row)
    return out


def inspect_table(data: bytes) -> dict:
    rows = parse_table(data)
    return {"count": sum(1 for r in rows if r.title),
            "rows": [{"number": r.number, "title": r.title, "type": r.node_type, "date": r.date[0] if r.date else None,
                      "builds_on": r.builds_on, "key": r.key, "problems": r.problems} for r in rows]}


def import_table(ledger, data: bytes, project_id: str) -> dict:
    if project_id not in {p.id for p in ledger.projects()}:
        raise LedgerError("unknown project")
    ids: dict[int, str] = {}
    for r in parse_table(data):
        if not r.title:
            continue
        ids[r.number] = ledger.create_entry(EntryInput(
            project_id=project_id, node_type=r.node_type, title=r.title, body=r.text or None,
            relations=[{"to": ids[x], "rel": "uses"} for x in dict.fromkeys(r.builds_on) if x in ids],
            milestone=r.key, import_info=_claimed(r.date),
        ))
    return {"imported": len(ids)}


def table_template(lang: str) -> bytes:
    if lang == "zh":
        rows = [["日期", "类型", "标题", "内容", "用到", "关键步骤"],
                ["2025-09-14", "想法", "流速会趋于饱和", "一页旧笔记", "", ""],
                ["2025-10", "假设", "饱和遵循幂律", "", "1", ""],
                ["2025-11-02", "实验", "数值实验 1", "指数约为 1.3", "2", "是"]]
    else:
        rows = [["date", "type", "title", "text", "builds on", "key step"],
                ["2025-09-14", "idea", "Flow speed levels off", "An old notebook page", "", ""],
                ["2025-10", "hypothesis", "Saturation follows a power law", "", "1", ""],
                ["2025-11-02", "experiment", "Numerical experiment 1", "The exponent is about 1.3", "2", "yes"]]
    return _csv(rows)


def _csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")  # the mark makes Excel read it as UTF-8


def steps_table(snap, blobs, project_id: str | None) -> bytes:
    """Every step of a project as a table: number, dates, kind, title, text, relations, marks."""
    from app.services.views import REL_LABELS, node_type_label

    state = snap.state
    entries = sorted((e for e in state.entries.values() if project_id in (None, e.project_id)), key=lambda e: e.seq)
    seq = {e.id: e.seq for e in state.entries.values()}
    rows = [[tr("Step"), tr("Date"), tr("Date stamp"), tr("Earlier date (the author's statement)"), tr("Type"),
             tr("Title"), tr("Text"), tr("Builds on"), tr("Key step"), tr("Withdrawn"), tr("Reference"), tr("Files")]]
    for e in entries:
        when = snap.when(e.id)
        body = ""
        files = snap.files.get(e.id, [])
        text_file = next((f for f in files if f.role == "body"), None)
        if text_file is not None and blobs is not None:
            try:
                body = blobs.get(text_file.sha256).decode("utf-8", errors="replace")
            except (OSError, ValueError):
                body = ""
        links = [f"#{seq.get(x.target, '?')} {tr(REL_LABELS.get(x.rel, x.rel))}" for x in state.edges
                 if x.source == e.id and x.active]
        ext = e.payload.get("external") or {}
        ref = (f"{ext.get('repo_url', '')} @ {ext['commit'][:12]}" if ext.get("commit")
               else f"https://doi.org/{ext['doi']}" if ext.get("doi") else ext.get("url", ""))
        imp = e.payload.get("import") or {}
        rows.append([f"#{e.seq}", when["time"][:10], "✓" if when["verified"] else "", imp.get("claimed_date", ""),
                     node_type_label(e.node_type), e.title, body, "; ".join(links), "★" if e.milestone else "",
                     "✕" if e.retracted_by else "", ref, "; ".join(f.name for f in files if f.role == "file")])
    return _csv(rows)
