"""Desktop control panel, isolated from game rules and rendering."""


def main():
    import os
    import sys
    from pathlib import Path

    # Match the replay utility's support for standalone Python distributions.
    for variable, folder, script in (("TCL_LIBRARY", "tcl8.6", "init.tcl"),
                                     ("TK_LIBRARY", "tk8.6", "tk.tcl")):
        bundled = Path(sys.base_prefix) / "lib" / folder
        if (bundled / script).is_file():
            os.environ.setdefault(variable, str(bundled))
    try:
        from .ui import Launcher
        import tkinter as tk
    except ImportError as exc:
        raise SystemExit('The launcher requires a Python installation with Tkinter support.') from exc
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
