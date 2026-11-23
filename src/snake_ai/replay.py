"""Read-only, row-by-row JSONL viewer. Never contacts a model or simulates moves."""
import argparse
import json
import os
import sys
from pathlib import Path


class Replay:
    def __init__(self, path):
        self.path = Path(path)
        self.rows = []
        self.states = []
        self.state_rows = []
        state = None
        state_row = None
        with self.path.open(encoding="utf-8-sig") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("expected a JSON object")
                except ValueError as exc:
                    raise ValueError(f"Row {number}: {exc}") from exc
                candidate = row.get("state") or row.get("initial_state")
                if candidate is None and isinstance(row.get("payload"), dict):
                    candidate = row["payload"].get("state")
                if candidate is not None:
                    self.validate_state(candidate, number)
                    state, state_row = candidate, number
                self.rows.append(row)
                self.states.append(state)
                self.state_rows.append(state_row)
        if not self.rows:
            raise ValueError("The log file is empty.")
        self.index = 0

    @staticmethod
    def validate_state(state, number):
        try:
            board = state["board"]
            for key in ("width", "height"):
                value = board[key]
                if type(value) is not int or not 1 <= value <= 200:
                    raise ValueError("board dimensions must be integers from 1 to 200")
            for key in ("snake", "food"):
                if not isinstance(state[key], list):
                    raise ValueError(f"{key} must be a list")
                for point in state[key]:
                    if len(point) != 2 or any(type(v) is not int for v in point):
                        raise ValueError(f"invalid {key} coordinates")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Row {number}: invalid game state ({exc})") from exc

    def move(self, delta):
        self.index = max(0, min(len(self.rows) - 1, self.index + delta))


def main():
    # Some standalone Python builds retain build-machine Tcl search paths.
    # Prefer their bundled scripts when the caller has not configured a path.
    for variable, folder, script in (("TCL_LIBRARY", "tcl8.6", "init.tcl"),
                                     ("TK_LIBRARY", "tk8.6", "tk.tcl")):
        bundled = Path(sys.base_prefix) / "lib" / folder
        if (bundled / script).is_file():
            os.environ.setdefault(variable, str(bundled))
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    parser = argparse.ArgumentParser(description="Inspect Snake AI JSONL logs")
    parser.add_argument("log", nargs="?", help="Optional log path; otherwise show a file picker")
    args = parser.parse_args()
    root = tk.Tk()
    root.withdraw()
    replay = None

    def select_file(path=None):
        nonlocal replay
        if path is None:
            # Cocoa file panels need a mapped parent and a running event loop.
            root.deiconify()
            root.lift()
            root.update_idletasks()
            path = filedialog.askopenfilename(
                parent=root, title="Select a Snake AI log",
                initialdir=str(Path.cwd() / "logs"),
                filetypes=[("JSON Lines logs", "*.jsonl"), ("All files", "*")])
        if not path:
            return False
        try:
            loaded = Replay(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot open log", str(exc), parent=root)
            return False
        replay = loaded
        return True

    root.title("Snake AI | Log board")
    root.configure(bg="#0f1724")
    toolbar = ttk.Frame(root, padding=8)
    toolbar.pack(fill="x")
    row_label = ttk.Label(toolbar)
    row_label.pack(side="left", padx=8)
    canvas = tk.Canvas(root, bg="#0f1724", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    detail = tk.Toplevel(root)
    detail.withdraw()
    detail.title("Snake AI | Selected row JSON")
    tabs = ttk.Notebook(detail)
    tabs.pack(fill="both", expand=True)
    row_text = ScrolledText(tabs, wrap="none", font=("Menlo", 12), width=70, height=32)
    decoded = ScrolledText(tabs, wrap="none", font=("Menlo", 12), width=70, height=32)
    for widget, label in ((row_text, "Selected row"), (decoded, "Decoded response")):
        tabs.add(widget, text=label)
        # Keep arrows for row navigation even when the JSON has keyboard focus.
        widget.bind("<Up>", lambda event: navigate(-1))
        widget.bind("<Down>", lambda event: navigate(1))
    detail.protocol("WM_DELETE_WINDOW", root.destroy)

    def replace(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")
        widget.yview_moveto(0)
        widget.xview_moveto(0)

    def render():
        if replay is None:
            row_label.configure(text="No log selected")
            canvas.configure(width=720, height=540)
            canvas.delete("all")
            canvas.create_text(20, 30, anchor="nw", fill="white",
                               text="Choose Open log… to select a log file.", font=("Arial", 16))
            return
        detail.deiconify()
        row = replay.rows[replay.index]
        state = replay.states[replay.index]
        number = replay.index + 1
        row_label.configure(text=f"Row {number} / {len(replay.rows)}   |   {row.get('event', 'unknown')}")
        root.title(f"Snake AI | {replay.path.name}")
        replace(row_text, json.dumps(row, indent=2, ensure_ascii=False))
        raw = row.get("raw")
        try:
            response = json.loads(raw) if isinstance(raw, str) else None
            response_text = json.dumps(response, indent=2, ensure_ascii=False) if response is not None else "This row has no encoded response."
        except ValueError:
            response_text = raw
        replace(decoded, response_text)
        canvas.delete("all")
        if state is None:
            canvas.configure(width=720, height=540)
            canvas.create_text(20, 30, anchor="nw", fill="white", text="No game state recorded at or before this row.")
            return
        width, height = state["board"]["width"], state["board"]["height"]
        # Logs record grid dimensions, not original pixel window dimensions.
        cell, top = 30, 90
        canvas.configure(width=(width + 3) * cell, height=(height + 3) * cell + top)
        canvas.create_text(18, 14, anchor="nw", fill="#e0eaf4", text=(
            f"Score {state.get('score', '?')}   Step {state.get('step', '?')}   Direction {state.get('direction', '?')}\n"
            f"State from row {replay.state_rows[replay.index]}   |   {state.get('outcome') or 'In progress'}\n"
            "↑ Previous row    ↓ Next row    Esc Close"), font=("Arial", 14))
        # Keep coordinate labels outside the margin used for fatal positions.
        canvas.create_text(15, top + 15, text="x/y", fill="#9fb4ca", font=("Arial", 10))
        for x in range(width):
            canvas.create_text((x + 2.5) * cell, top + 15, text=str(x),
                               fill="#c7d8e8", font=("Arial", 12), tags="column_label")
        for y in range(height):
            canvas.create_text(15, top + (y + 2.5) * cell, text=str(y),
                               fill="#c7d8e8", font=("Arial", 12), tags="row_label")
        for y in range(height):
            for x in range(width):
                canvas.create_rectangle((x+2)*cell, top+(y+2)*cell, (x+3)*cell, top+(y+3)*cell,
                                        outline="#263749")
        for i, (x, y) in enumerate(state["snake"]):
            # A one-cell margin makes fatal out-of-bounds head positions visible.
            color = "#90ffc9" if i == 0 else "#45d69c"
            if not (0 <= x < width and 0 <= y < height):
                color = "#ff7373"
            canvas.create_rectangle((x+2)*cell+2, top+(y+2)*cell+2,
                                    (x+3)*cell-2, top+(y+3)*cell-2, fill=color, outline="")
        for x, y in state["food"]:
            cx, cy = (x+2.5)*cell, top+(y+2.5)*cell
            canvas.create_oval(cx-9, cy-9, cx+9, cy+9, fill="#ff7373", outline="")

    def navigate(delta):
        if replay is None:
            return "break"
        replay.move(delta)
        render()
        return "break"

    def open_another():
        if select_file():
            render()

    ttk.Button(toolbar, text="Open log…", command=open_another).pack(side="right")
    ttk.Button(toolbar, text="Next ↓", command=lambda: navigate(1)).pack(side="right")
    ttk.Button(toolbar, text="Previous ↑", command=lambda: navigate(-1)).pack(side="right")
    for window in (root, detail):
        window.bind("<Up>", lambda event: navigate(-1))
        window.bind("<Down>", lambda event: navigate(1))
        window.bind("<Escape>", lambda event: root.destroy())
    render()
    root.geometry("+20+40")
    root.deiconify()
    root.update_idletasks()
    detail.geometry(f"+{root.winfo_x() + root.winfo_width() + 12}+40")
    def initial_selection():
        if select_file(args.log):
            render()
            root.update_idletasks()
            detail.geometry(f"+{root.winfo_x() + root.winfo_width() + 12}+40")

    # Open the modal picker only after Tk has mapped the main window.
    # Cancellation leaves Open log available instead of an invisible Dock app.
    root.after(150, initial_selection)
    root.mainloop()


if __name__ == "__main__":
    main()
