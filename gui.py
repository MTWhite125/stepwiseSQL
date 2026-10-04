"""Tk desktop database studio: local database or connection to the HTTP server."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import tkinter as tk
from tkinter import ttk
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from service import DatabaseService


class RemoteService:
    def __init__(self, url):
        self.url = url.rstrip("/")

    def request(self, path, data=None):
        request = Request(self.url + path,
                          data=json.dumps(data).encode() if data is not None else None,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as exc:
            raise ValueError(json.load(exc).get("error", str(exc))) from exc

    def schema(self):
        return self.request("/api/schema")["schema"]

    def execute(self, sql):
        return self.request("/api/query", {"sql": sql})


class Studio:
    def __init__(self, root, service, label):
        self.root, self.service = root, service
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        root.title("Mini SQLite Studio — " + label)
        root.geometry("1050x720")
        root.minsize(700, 480)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Mini SQLite Studio", font=("Helvetica", 22, "bold")).pack(anchor="w")
        ttk.Label(frame, text=label).pack(anchor="w", pady=(4, 16))
        panes = ttk.Panedwindow(frame, orient="horizontal")
        panes.pack(fill="both", expand=True)
        sidebar, editor = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(sidebar, weight=1)
        panes.add(editor, weight=4)
        ttk.Label(sidebar, text="Tables", font=("Helvetica", 14, "bold")).pack(anchor="w")
        self.tables = ttk.Treeview(sidebar, columns=("rows",), show="tree headings", height=12)
        self.tables.heading("#0", text="Name")
        self.tables.heading("rows", text="Rows")
        self.tables.column("#0", width=140)
        self.tables.column("rows", width=55)
        self.tables.pack(fill="both", expand=True, pady=8)
        self.tables.bind("<Double-1>", self.browse)
        self.refresh = ttk.Button(sidebar, text="Refresh schema", command=self.load_schema)
        self.refresh.pack(anchor="w")
        self.details = tk.StringVar(value="Double-click a table to browse.")
        ttk.Label(sidebar, textvariable=self.details, wraplength=220).pack(anchor="w", pady=10)
        self.tables.bind("<<TreeviewSelect>>", self.describe)
        ttk.Label(editor, text="SQL — one statement at a time").pack(anchor="w")
        self.sql = tk.Text(editor, height=8, font=("Courier", 13), wrap="word", undo=True)
        self.sql.pack(fill="x", pady=8)
        self.sql.insert("1.0", "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);")
        self.run_button = ttk.Button(editor, text="Run statement", command=self.run)
        self.run_button.pack(anchor="w")
        root.bind("<Control-Return>", lambda event: self.run())
        root.bind("<Command-Return>", lambda event: self.run())
        self.status = tk.StringVar(value="Ready")
        ttk.Label(editor, textvariable=self.status, wraplength=650).pack(anchor="w", pady=12)
        result_frame = ttk.Frame(editor)
        result_frame.pack(fill="both", expand=True)
        self.results = ttk.Treeview(result_frame, show="headings")
        vertical = ttk.Scrollbar(result_frame, orient="vertical", command=self.results.yview)
        horizontal = ttk.Scrollbar(result_frame, orient="horizontal", command=self.results.xview)
        self.results.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.results.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)
        self.schema_data = {}
        self.load_schema()

    def submit(self, work, done):
        if self.pending is not None:
            return
        self.run_button.state(["disabled"])
        self.refresh.state(["disabled"])
        self.status.set("Working…")
        self.pending = self.pool.submit(work)

        def poll():
            if not self.pending.done():
                self.root.after(50, poll)
                return
            future, self.pending = self.pending, None
            try:
                done(future.result())
            except Exception as exc:
                self.status.set(f"Error: {exc}")
            finally:
                self.run_button.state(["!disabled"])
                self.refresh.state(["!disabled"])
        self.root.after(50, poll)

    def set_schema(self, schema):
        self.schema_data = schema
        self.tables.delete(*self.tables.get_children())
        for name, table in schema.items():
            self.tables.insert("", "end", iid=name, text=name, values=(table["row_count"],))

    def load_schema(self):
        def done(schema):
            self.set_schema(schema)
            self.status.set("Schema refreshed")
        self.submit(self.service.schema, done)

    def describe(self, event=None):
        selection = self.tables.selection()
        if selection:
            columns = self.schema_data[selection[0]]["columns"]
            self.details.set("\n".join(c["name"] + ": " + c["type"] +
                                       (" (PK)" if c["primary"] else "") for c in columns))

    def browse(self, event=None):
        selection = self.tables.selection()
        if selection:
            self.sql.delete("1.0", "end")
            self.sql.insert("1.0", f"SELECT * FROM {selection[0]};")
            self.run()

    def run(self):
        sql = self.sql.get("1.0", "end").strip()

        def done(data):
            self.set_schema(data["schema"])
            self.results.delete(*self.results.get_children())
            result = data["result"]
            columns = list(result[0]) if isinstance(result, list) and result else []
            self.results.configure(columns=columns)
            for col in columns:
                self.results.heading(col, text=col)
                self.results.column(col, width=150, stretch=True)
            if isinstance(result, list):
                for row in result:
                    self.results.insert("", "end", values=["NULL" if row[c] is None else row[c] for c in columns])
                self.status.set(f"{len(result)} rows returned")
            else:
                self.status.set(result)
        self.submit(lambda: self.service.execute(sql), done)

    def close(self):
        self.pool.shutdown(wait=False)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="?", default="mini.db")
    parser.add_argument("--server", help="Connect to an existing server, e.g. http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        service = RemoteService(args.server) if args.server else DatabaseService(args.database)
        root = tk.Tk()
        Studio(root, service, args.server or args.database)
        root.mainloop()
    except (ValueError, OSError, tk.TclError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
