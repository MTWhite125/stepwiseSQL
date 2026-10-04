# Mini SQLite in Python

A small educational SQL database implemented from scratch using only the Python
standard library. It does not use `sqlite3`. Requires Python 3.8 or newer.

The project includes a persistent database engine, Tk desktop GUI, HTTP JSON API,
and browser SQL studio. No pip packages are required. The desktop GUI needs a
Python installation with Tkinter (verified here with Python 3.14.0 / Tk 8.6).

## Desktop GUI

```sh
cd /Users/mtwhite/projects/mini_sqlite
python3 gui.py demo.db
```

Write SQL in the editor and click **Run statement** (or Ctrl/Command+Enter).
Query results appear in a scrollable grid. The sidebar displays tables, row
counts, and column types; double-click a table to browse it. SQL errors appear
in the status area. Queries run in a worker thread to keep the GUI responsive.

## Web server and browser GUI

```sh
python3 server.py demo.db --port 8000
```

Open **http://127.0.0.1:8000** in a browser. The page includes a SQL editor,
table browser, result grid, and error messages. Stop the server with Ctrl+C.

To use the desktop GUI and browser against the same live database, start the
server first, then connect the GUI:

```sh
python3 gui.py --server http://127.0.0.1:8000
```

Do not open the same file in separate standalone GUI, CLI, or server processes:
only the server should own the file when sharing access. Server requests are
serialized through a lock, so concurrent clients cannot interleave writes.

### HTTP API

- `GET /api/schema`: returns `{"schema": {"table": {"columns": [...], "row_count": 0}}}`.
- `POST /api/query`: accepts `{"sql": "SELECT * FROM users;"}` and returns
  `{"result": [...], "schema": {...}}`; writes return a result message instead.
- Invalid SQL returns HTTP 400 with `{"error": "..."}`.

```sh
curl http://127.0.0.1:8000/api/schema
curl -X POST http://127.0.0.1:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT * FROM users;"}'
```

The server defaults to localhost. It is a local development tool with no
authentication or TLS; do not expose it to untrusted networks. JSON requests
are limited to 64 KiB and cross-origin browser writes are rejected.

## Verify

```sh
python3 -m unittest -v
python3 smoke_gui.py
```

The automated suite checks CRUD, NULL handling, constraints, statement rollback,
persistence, HTTP errors, and concurrent HTTP inserts. The GUI smoke test opens
a real desktop window, runs a query, verifies its grid, and closes automatically.

## Run

```sh
cd /Users/mtwhite/projects/mini_sqlite
python3 mini_sqlite.py demo.db
```

Enter one statement per line:

```sql
CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);
INSERT INTO users VALUES (1, 'Ada', 28);
INSERT INTO users (id, name) VALUES (2, 'Grace');
SELECT * FROM users;
SELECT name FROM users WHERE age >= 18;
UPDATE users SET age = 29 WHERE id = 1;
DELETE FROM users WHERE id = 2;
```

Use `.tables`, `.schema`, and `.quit` in the shell. Tables and rows survive
restarts. You can also execute a single command:

```sh
python3 mini_sqlite.py demo.db -c "SELECT * FROM users;"
python3 -m unittest -v
```

## Python API

```python
from mini_sqlite import Database

db = Database(":memory:")  # Or a file path for persistence
db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
db.execute("INSERT INTO items VALUES (1, 'example')")
rows = db.execute("SELECT * FROM items")
print(rows)  # [{'id': 1, 'label': 'example'}]
```

## Supported subset and limits

- `CREATE TABLE`, `DROP TABLE`, `INSERT`, `SELECT`, `UPDATE`, and `DELETE`.
- Types: `INTEGER`, `REAL`, and `TEXT`; values may also be `NULL`.
- One optional column-level `PRIMARY KEY`, checked for uniqueness and non-null values.
- Optional single `WHERE` condition with `=`, `!=`, `<>`, `<`, `>`, `<=`, `>=`,
  `IS NULL`, or `IS NOT NULL`.
- Case-insensitive unquoted identifiers; single-quoted strings use doubled quotes
  to escape an apostrophe, such as `'O''Brien'`.
- Failed statements restore the prior in-memory state. Successful writes flush
  a temporary JSON file and atomically replace the database file.

This is a SQLite-style learning project, not SQLite file-format compatible.
It keeps the entire database in memory and scans rows directly. It supports one
process at a time, with no locking, indexes, joins, sorting, explicit transactions,
SQL comments, multiline shell statements, or full SQLite type/coercion semantics.
Files use JSON even when named `.db`. Atomic replacement is not a complete
power-loss durability guarantee.
