import tempfile
import unittest
from pathlib import Path

from mini_sqlite import Database, DatabaseError


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
        self.db.execute("INSERT INTO users VALUES (1, 'O''Brien', 30)")
        self.db.execute("INSERT INTO users (id, name) VALUES (2, 'Ada')")

    def test_crud(self):
        self.assertEqual(self.db.execute("SELECT name FROM users WHERE age >= 20"), [{"name": "O'Brien"}])
        self.assertEqual(self.db.execute("UPDATE users SET age = 25 WHERE id = 2"), "1 rows updated")
        self.assertEqual(self.db.execute("DELETE FROM users WHERE age < 28"), "1 rows deleted")
        self.assertEqual(len(self.db.execute("SELECT * FROM users")), 1)
        self.db.execute("DROP TABLE users")
        self.assertEqual(self.db.tables, {})

    def test_null(self):
        self.assertEqual(self.db.execute("SELECT id FROM users WHERE age IS NULL"), [{"id": 2}])
        self.assertEqual(self.db.execute("SELECT id FROM users WHERE age = NULL"), [])

    def test_errors_are_atomic(self):
        before = self.db.execute("SELECT * FROM users")
        for statement in (
            "INSERT INTO users VALUES (1, 'Duplicate', 10)",
            "UPDATE users SET id = 3",
            "UPDATE users SET age = 'bad'",
            "DELETE FROM users; DROP TABLE users",
            "SELECT missing FROM users",
            "INSERT INTO users VALUES (NULL, 'Bad', 10)",
            "INSERT INTO users VALUES (3, 'Bad')",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(DatabaseError):
                    self.db.execute(statement)
                self.assertEqual(self.db.execute("SELECT * FROM users"), before)

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            db = Database(path)
            db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, price REAL)")
            db.execute("INSERT INTO items VALUES (1, 2.5)")
            contents = path.read_bytes()
            with self.assertRaises(DatabaseError):
                db.execute("INSERT INTO items VALUES (1, 3.5)")
            self.assertEqual(path.read_bytes(), contents)
            self.assertEqual(Database(path).execute("SELECT * FROM items"), [{"id": 1, "price": 2.5}])


if __name__ == "__main__":
    unittest.main()
