"""
VLINE – Vehicle Licence Interpretation and Number Extraction
Entry point – run this file to launch the dashboard.

    python main.py

Requirements: see requirements.txt
"""

import sys
import tkinter as tk


def main():
    # Apply Sun Valley dark theme BEFORE building widgets
    # so custom style overrides in VlineApp work correctly.
    root = tk.Tk()
    root.withdraw()  # hide the temporary root

    try:
        import sv_ttk
        sv_ttk.set_theme("dark")
    except ImportError:
        pass  # graceful fallback if sv_ttk not installed

    root.destroy()

    from dashboard import VlineApp
    app = VlineApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
