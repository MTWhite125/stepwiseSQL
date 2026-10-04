"""Thread-safe application layer shared by the HTTP server and desktop GUI."""
import copy
import threading

from mini_sqlite import Database, DatabaseError


class DatabaseService:
    def __init__(self, filename):
        self.database = Database(filename)
        self.lock = threading.RLock()

    def schema(self):
        with self.lock:
            return {name: {"columns": copy.deepcopy(table["columns"]),
                           "row_count": len(table["rows"])}
                    for name, table in self.database.tables.items()}

    def execute(self, sql):
        if not isinstance(sql, str) or not sql.strip():
            raise DatabaseError("Provide a non-empty SQL string")
        with self.lock:
            result = self.database.execute(sql)
            return {"result": result, "schema": self.schema()}
