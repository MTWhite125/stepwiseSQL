"""A tiny SQL database, implemented without sqlite3 or external dependencies."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import tempfile


class DatabaseError(ValueError):
    pass


class Parser:
    token = re.compile(r"\s*(?:('(?:''|[^'])*')|(-?\d+(?:\.\d+)?)|([A-Za-z_][A-Za-z_0-9]*)|(<=|>=|<>|!=|[(),;*=<>]))")

    def __init__(self, sql):
        self.tokens = []
        pos = 0
        while pos < len(sql):
            if not sql[pos:].strip():
                break
            match = self.token.match(sql, pos)
            if not match:
                raise DatabaseError(f"Unexpected input: {sql[pos:pos + 20]!r}")
            self.tokens.append(match.group(0).strip())
            pos = match.end()
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ""

    def pop(self):
        value = self.peek()
        if not value:
            raise DatabaseError("Unexpected end of SQL")
        self.pos += 1
        return value

    def accept(self, value):
        if self.peek().upper() == value:
            self.pos += 1
            return True
        return False

    def expect(self, value):
        if not self.accept(value):
            raise DatabaseError(f"Expected {value}, got {self.peek()!r}")

    def name(self):
        value = self.pop()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value):
            raise DatabaseError(f"Expected identifier, got {value!r}")
        return value.lower()

    def literal(self):
        value = self.pop()
        if value.startswith("'"):
            return value[1:-1].replace("''", "'")
        if value.upper() == "NULL":
            return None
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            raise DatabaseError(f"Expected a number, quoted string, or NULL: {value!r}") from None

    def finish(self):
        self.accept(";")
        if self.peek():
            raise DatabaseError(f"Unexpected token: {self.peek()!r}")


class Database:
    """Single-process database. Each successful write atomically replaces a JSON file."""

    def __init__(self, filename=":memory:"):
        self.path = None if str(filename) == ":memory:" else Path(filename)
        self.tables = {}
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if data.get("format") != "mini-sqlite-v1" or not isinstance(data.get("tables"), dict):
                    raise ValueError("unrecognized database format")
                self.tables = data["tables"]
            except (ValueError, AttributeError) as exc:
                raise DatabaseError(f"Cannot load database: {exc}") from exc

    def _save(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as stream:
                name = stream.name
                json.dump({"format": "mini-sqlite-v1", "tables": self.tables}, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _column(table, name):
        for column in table["columns"]:
            if column["name"] == name:
                return column
        raise DatabaseError(f"Unknown column: {name}")

    def _validate(self, table, row):
        for col in table["columns"]:
            value = row[col["name"]]
            kind = col["type"]
            if value is None:
                if col["primary"]:
                    raise DatabaseError("PRIMARY KEY cannot be NULL")
            elif (kind == "INTEGER" and type(value) is not int or
                  kind == "REAL" and type(value) not in (int, float) or
                  kind == "TEXT" and not isinstance(value, str)):
                raise DatabaseError(f"{col['name']} requires {kind}")
        for col in table["columns"]:
            if col["primary"]:
                values = [r[col["name"]] for r in table["rows"]]
                if len(set(values)) != len(values):
                    raise DatabaseError("Duplicate PRIMARY KEY")

    def _where(self, parser, table):
        if not parser.accept("WHERE"):
            return lambda row: True
        name = parser.name()
        self._column(table, name)
        if parser.accept("IS"):
            negate = parser.accept("NOT")
            parser.expect("NULL")
            return lambda row: (row[name] is not None) if negate else (row[name] is None)
        op = parser.pop()
        if op not in ("=", "!=", "<>", "<", ">", "<=", ">="):
            raise DatabaseError(f"Unsupported operator: {op}")
        value = parser.literal()

        def matches(row):
            left = row[name]
            if left is None or value is None:
                return False
            if op == "=":
                return left == value
            if op in ("!=", "<>"):
                return left != value
            try:
                return {"<": lambda: left < value, ">": lambda: left > value,
                        "<=": lambda: left <= value, ">=": lambda: left >= value}[op]()
            except TypeError:
                raise DatabaseError("Cannot compare these value types") from None
        return matches

    def execute(self, sql):
        """Execute one SQL statement; SELECT returns a list of dictionaries."""
        before = copy.deepcopy(self.tables)
        try:
            result, changed = self._execute(Parser(sql))
            if changed:
                self._save()
            return result
        except Exception:
            self.tables = before
            raise

    def _execute(self, p):
        command = p.pop().upper()
        if command == "CREATE":
            p.expect("TABLE")
            name = p.name()
            if name in self.tables:
                raise DatabaseError(f"Table already exists: {name}")
            p.expect("(")
            columns = []
            while True:
                column = p.name()
                kind = p.pop().upper()
                if kind not in ("INTEGER", "REAL", "TEXT"):
                    raise DatabaseError("Supported types: INTEGER, REAL, TEXT")
                primary = p.accept("PRIMARY")
                if primary:
                    p.expect("KEY")
                if column in [c["name"] for c in columns]:
                    raise DatabaseError(f"Duplicate column: {column}")
                columns.append({"name": column, "type": kind, "primary": primary})
                if not p.accept(","):
                    break
            p.expect(")")
            p.finish()
            if sum(c["primary"] for c in columns) > 1:
                raise DatabaseError("Only one PRIMARY KEY is supported")
            self.tables[name] = {"columns": columns, "rows": []}
            return "Table created", True
        if command == "INSERT":
            p.expect("INTO")
        elif command == "DELETE":
            p.expect("FROM")
        elif command == "DROP":
            p.expect("TABLE")
        elif command == "SELECT":
            selected = []
            if p.accept("*"):
                selected = None
            else:
                selected.append(p.name())
                while p.accept(","):
                    selected.append(p.name())
            p.expect("FROM")
        elif command != "UPDATE":
            raise DatabaseError(f"Unsupported command: {command}")
        name = p.name()
        if name not in self.tables:
            raise DatabaseError(f"Unknown table: {name}")
        table = self.tables[name]
        if command == "DROP":
            p.finish()
            del self.tables[name]
            return "Table dropped", True
        if command == "INSERT":
            names = [c["name"] for c in table["columns"]]
            if p.accept("("):
                names = [p.name()]
                while p.accept(","):
                    names.append(p.name())
                p.expect(")")
            if len(set(names)) != len(names):
                raise DatabaseError("Duplicate insert column")
            for column in names:
                self._column(table, column)
            p.expect("VALUES")
            p.expect("(")
            values = [p.literal()]
            while p.accept(","):
                values.append(p.literal())
            p.expect(")")
            p.finish()
            if len(names) != len(values):
                raise DatabaseError("Column and value counts differ")
            row = dict.fromkeys(c["name"] for c in table["columns"])
            row.update(zip(names, values))
            table["rows"].append(row)
            self._validate(table, row)
            return "1 row inserted", True
        if command == "UPDATE":
            p.expect("SET")
            updates = {}
            while True:
                column = p.name()
                self._column(table, column)
                p.expect("=")
                updates[column] = p.literal()
                if not p.accept(","):
                    break
        predicate = self._where(p, table)
        p.finish()
        rows = [row for row in table["rows"] if predicate(row)]
        if command == "SELECT":
            if selected is None:
                selected = [c["name"] for c in table["columns"]]
            for column in selected:
                self._column(table, column)
            return [{c: row[c] for c in selected} for row in rows], False
        if command == "DELETE":
            chosen = {id(row) for row in rows}
            table["rows"] = [row for row in table["rows"] if id(row) not in chosen]
            return f"{len(rows)} rows deleted", True
        for row in rows:
            row.update(updates)
        for row in table["rows"]:
            self._validate(table, row)
        return f"{len(rows)} rows updated", True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="?", default="mini.db")
    parser.add_argument("-c", "--command", help="Execute one SQL statement and exit")
    args = parser.parse_args()
    try:
        database = Database(args.database)
        if args.command:
            result = database.execute(args.command)
            print(json.dumps(result, indent=2) if isinstance(result, list) else result)
            return
        print("Mini SQLite — one statement per line; .tables, .schema, .quit")
        while True:
            try:
                sql = input("mini> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if sql in (".quit", ".exit"):
                break
            if not sql:
                continue
            if sql == ".tables":
                print(" ".join(database.tables))
                continue
            if sql == ".schema":
                for name, table in database.tables.items():
                    columns = ", ".join(c["name"] + " " + c["type"] +
                                        (" PRIMARY KEY" if c["primary"] else "") for c in table["columns"])
                    print(f"CREATE TABLE {name} ({columns});")
                continue
            try:
                result = database.execute(sql)
                print(json.dumps(result, indent=2) if isinstance(result, list) else result)
            except (DatabaseError, OSError) as exc:
                print(f"Error: {exc}")
    except (DatabaseError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
