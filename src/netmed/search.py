"""Keyword search over discovered operations of all catalog sources.

The index is built with the catalog: one SQLite FTS5 table (Porter stemming,
BM25 ranking) over operation names, first documentation paragraphs, parameter
names and the source's overview description. API commands come from
Restish's native help, so no OpenAPI document is parsed here. Text is taken from the sources'
own interfaces; nothing is written for search purposes. Queries read only
matching rows, so searching does not load discovery files.
"""

import re
import sqlite3
from pathlib import Path

DEFAULT_LIMIT = 10
PER_SOURCE = 2
# Ranked rows read per query round before the per-source limit is applied.
CHUNK = 400
# Rows written per executemany call while building the index.
BATCH = 5000
# BM25 weights per column: name, summary, parameters, source description.
WEIGHTS = (3.0, 1.0, 0.5, 1.0)
SUMMARY_CHARACTERS = 300
DISPLAY_CHARACTERS = 120
STOP_WORDS = frozenset(
    "a an and are as at be by for from has in is it its of on or that the to "
    "was were will with this these those into via using use used can may".split()
)


def index_path(catalog_path):
    catalog_path = Path(catalog_path)
    return catalog_path.parent / (catalog_path.stem + "-search.sqlite")


def split_identifiers(text):
    """Split snake_case, kebab-case, dotted paths and camelCase into words."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return re.sub(r"[_\-./:{}]+", " ", text)


def first_paragraph(text, limit=SUMMARY_CHARACTERS):
    paragraph = re.split(r"\n\s*\n", (text or "").strip(), maxsplit=1)[0]
    return re.sub(r"\s+", " ", paragraph)[:limit]


# Python naming convention for exception types; not tools an agent searches for.
EXCEPTION_SUFFIXES = ("Error", "Exception", "Warning")


def python_documents(name, metadata, module):
    from .importers.python import package_member

    for path, item in (metadata.get("operations") or {}).items():
        parts = path.split(".")
        if any(part.startswith("_") for part in parts):
            continue
        if any(part.endswith(EXCEPTION_SUFFIXES) for part in parts):
            continue
        # Foreign re-exports are hidden from help overviews; keep search aligned.
        if not package_member(item, module):
            continue
        yield (
            name,
            f"netmed {name} {path.replace('.', ' ')}",
            path,
            first_paragraph(item.get("doc")),
            " ".join(p["name"] for p in item.get("parameters") or []),
        )


def api_documents(name, rows):
    """Documents for API commands exactly as Restish's native help lists them."""
    for command, summary, group in rows:
        yield (name, f"netmed {name} {command}", f"{command} {group}", summary, "")


def unwrap(type_reference):
    while type_reference and type_reference.get("ofType"):
        type_reference = type_reference["ofType"]
    return (type_reference or {}).get("name")


def combined_description(field, child_type):
    """Field description plus its type's, unless the type repeats it."""
    own = (field.get("description") or "").strip()
    inherited = ((child_type or {}).get("description") or "").strip()
    if inherited and inherited not in own:
        own = f"{own} {inherited}".strip()
    return first_paragraph(own)


def graphql_documents(name, introspection):
    """Root query fields and the fields of the object types they return."""
    schema = introspection.get("data", introspection)["__schema"]
    types = {item["name"]: item for item in schema["types"]}
    root = types[schema["queryType"]["name"]]
    reached = {}
    for field in root.get("fields") or []:
        child = unwrap(field["type"])
        yield (
            name,
            f"netmed {name} query '{{ {field['name']} {{ ... }} }}'",
            f"{field['name']} {child or ''}",
            combined_description(field, types.get(child)),
            " ".join(argument["name"] for argument in field.get("args") or []),
        )
        if (types.get(child) or {}).get("kind") == "OBJECT":
            reached.setdefault(child, []).append(field["name"])
    for type_name, roots in reached.items():
        for field in types[type_name].get("fields") or []:
            child = unwrap(field["type"])
            yield (
                name,
                f"netmed {name} query '{{ {roots[0]} {{ {field['name']} }} }}'",
                f"{' '.join(roots)} {type_name} {field['name']} {child or ''}",
                combined_description(field, types.get(child)),
                " ".join(argument["name"] for argument in field.get("args") or []),
            )


def write_index(path, documents, descriptions):
    """Write the search index atomically from (source, call, name, summary, params)."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        # Contentless index (positions kept for BM25 column weights) plus a small
        # table with what results display; indexed text itself is not stored.
        connection.execute(
            "CREATE VIRTUAL TABLE operations USING fts5("
            "name, summary, params, source_text, content='', "
            "tokenize='porter unicode61')"
        )
        connection.execute(
            "CREATE TABLE entries (id INTEGER PRIMARY KEY, source TEXT, call TEXT, "
            "summary TEXT)"
        )
        indexed, displayed = [], []

        def flush():
            connection.executemany(
                "INSERT INTO operations(rowid, name, summary, params, source_text) "
                "VALUES (?, ?, ?, ?, ?)",
                indexed,
            )
            connection.executemany("INSERT INTO entries VALUES (?, ?, ?, ?)", displayed)
            indexed.clear()
            displayed.clear()

        for number, (source, call, name_text, summary, params) in enumerate(documents):
            indexed.append(
                (
                    number,
                    split_identifiers(name_text),
                    summary,
                    split_identifiers(params),
                    split_identifiers(source) + " " + descriptions.get(source, ""),
                )
            )
            displayed.append((number, source, call, summary[:DISPLAY_CHARACTERS]))
            if len(indexed) >= BATCH:
                flush()
        flush()
        connection.execute("INSERT INTO operations(operations) VALUES ('optimize')")
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()
    temporary.replace(path)


def query_terms(text):
    words = re.findall(r"[a-z0-9]+", split_identifiers(text).lower())
    return [word for word in words if len(word) > 1 and word not in STOP_WORDS]


def search(path, text, *, limit=DEFAULT_LIMIT, offset=0, source=None):
    """Return ranked results, at most PER_SOURCE per source unless one is selected."""
    path = Path(path)
    if not path.is_file():
        return None
    terms = query_terms(text)
    if not terms:
        return []
    match = " OR ".join('"' + term + '"' for term in terms)
    # Read-only and immutable: installed bundles are not writable.
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    )
    sql = (
        "SELECT e.source, e.call, e.summary, bm25(operations, ?, ?, ?, ?) AS score "
        "FROM operations JOIN entries e ON e.id = operations.rowid "
        "WHERE operations MATCH ?"
    )
    parameters = [*WEIGHTS, match]
    if source:
        sql += " AND e.source = ?"
        parameters.append(source)
    sql += " ORDER BY score LIMIT ? OFFSET ?"
    wanted = offset + limit
    results, per_source, scanned = [], {}, 0
    try:
        # Read ranked rows in chunks until the requested page is complete, so the
        # per-source limit never ends pagination early.
        while len(results) < wanted:
            rows = connection.execute(sql, [*parameters, CHUNK, scanned]).fetchall()
            scanned += len(rows)
            for source_name, call, display, score in rows:
                if not source and per_source.get(source_name, 0) >= PER_SOURCE:
                    continue
                per_source[source_name] = per_source.get(source_name, 0) + 1
                results.append(
                    {
                        "source": source_name,
                        "call": call,
                        "summary": display,
                        "score": -score,
                    }
                )
            if len(rows) < CHUNK:
                break
    finally:
        connection.close()
    return results[offset : offset + limit]
