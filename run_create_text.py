"""Entry point for PyInstaller (see create_text_app/README.md "アプリ化").

Kept at the repo root (rather than using create_text_app/__main__.py
directly) so PyInstaller's analysis starts from a script whose own
directory already contains both sibling packages (create_text_app,
davinci_auto_cut, silence_cut_app) it needs to resolve.
"""

from create_text_app.gui import main

if __name__ == "__main__":
    main()
