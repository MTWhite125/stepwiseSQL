"""Launch the real Tk GUI, exercise a query, and close after verification."""
import tkinter as tk
from gui import Studio
from service import DatabaseService


def main():
    service = DatabaseService(":memory:")
    service.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    service.execute("INSERT INTO users VALUES (1, 'Ada')")
    root = tk.Tk()
    studio = Studio(root, service, "GUI smoke test")
    failures = []

    def query():
        if studio.pending is not None:
            root.after(50, query)
            return
        studio.sql.delete("1.0", "end")
        studio.sql.insert("1.0", "SELECT * FROM users;")
        studio.run()
        root.after(50, verify)

    def verify():
        if studio.pending is not None:
            root.after(50, verify)
            return
        rows = studio.results.get_children()
        if len(rows) != 1 or studio.results.item(rows[0], "values") != ("1", "Ada"):
            failures.append("GUI did not display expected query result")
        studio.close()

    root.after(50, query)
    root.after(10000, lambda: (failures.append("GUI test timed out"), studio.close()))
    root.mainloop()
    if failures:
        raise AssertionError("; ".join(failures))
    print("GUI smoke test passed")


if __name__ == "__main__":
    main()
