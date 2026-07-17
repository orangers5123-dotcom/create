"""Entry point for PyInstaller (see silence_cut_app/README.md "アプリ化").

Kept at the repo root (rather than using silence_cut_app/__main__.py
directly) so PyInstaller's analysis starts from a script whose own
directory already contains both sibling packages (silence_cut_app,
davinci_auto_cut) it needs to resolve.
"""

from silence_cut_app.gui import main

if __name__ == "__main__":
    main()
