"""Install run.py into Resolve's Scripts menu (Workspace > Scripts > Edit).

Usage:
    python3 install.py

Copies a small launcher into Resolve's per-user "Scripts/Edit" folder so
"Auto Cut (Silence + Filler)" shows up in Resolve's Workspace > Scripts
menu. The launcher just adds this repo to sys.path and calls
davinci_auto_cut.run.main() with no arguments (dry-run, silence-only --
edit the launcher or run run.py directly for other options).
"""

import os
import platform
import shutil
import sys

LAUNCHER_NAME = "Auto Cut (Silence + Filler).py"

LAUNCHER_TEMPLATE = '''\
import sys

sys.path.insert(0, {repo_dir!r})

from davinci_auto_cut.run import main

if __name__ == "__main__":
    main([])
'''


def scripts_edit_dir() -> str:
    system = platform.system()
    home = os.path.expanduser("~")

    if system == "Darwin":
        return os.path.join(
            home, "Library", "Application Support", "Blackmagic Design",
            "DaVinci Resolve", "Fusion", "Scripts", "Edit",
        )
    if system == "Windows":
        appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        return os.path.join(
            appdata, "Blackmagic Design", "DaVinci Resolve", "Support",
            "Fusion", "Scripts", "Edit",
        )
    # Linux
    return os.path.join(
        home, ".local", "share", "DaVinciResolve", "Fusion", "Scripts", "Edit",
    )


def main() -> int:
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = scripts_edit_dir()

    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as exc:
        print(f"Could not create {target_dir}: {exc}", file=sys.stderr)
        return 1

    target_path = os.path.join(target_dir, LAUNCHER_NAME)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(LAUNCHER_TEMPLATE.format(repo_dir=repo_dir))

    print(f"Installed launcher to: {target_path}")
    print('Restart Resolve, then run it from Workspace > Scripts > Edit > "Auto Cut (Silence + Filler)".')
    return 0


if __name__ == "__main__":
    sys.exit(main())
