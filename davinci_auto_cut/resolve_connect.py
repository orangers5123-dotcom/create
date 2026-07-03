"""Connect to a running DaVinci Resolve instance.

This mirrors the bootstrap snippet Blackmagic ships in
"DaVinci Resolve/Scripting/Readme.txt". It works two ways:

- Run from inside Resolve (Workspace > Scripts, or the Console): a ``bmd``
  global is already injected by Resolve, so we just use it.
- Run as an external Python process: we locate ``DaVinciResolveScript``
  via the well-known per-OS install paths (or ``RESOLVE_SCRIPT_API`` /
  ``RESOLVE_SCRIPT_LIB`` env vars if already set) and import it.

Not runnable/testable outside of an actual Resolve install -- there is no
Resolve instance in this sandbox, so this module is written strictly to
the documented API and has not been execution-verified.
"""

import os
import sys
import platform


class ResolveConnectionError(RuntimeError):
    pass


def _ensure_env_paths() -> None:
    system = platform.system()

    if system == "Darwin":
        default_api = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        default_lib = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
    elif system == "Windows":
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        default_api = os.path.join(
            program_data, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting"
        )
        default_lib = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
    else:  # Linux
        default_api = "/opt/resolve/Developer/Scripting"
        default_lib = "/opt/resolve/libs/Fusion/fusionscript.so"
        if not os.path.isdir(default_api):
            # Some distros install under /home/resolve instead of /opt/resolve.
            alt_api = "/home/resolve/Developer/Scripting"
            if os.path.isdir(alt_api):
                default_api = alt_api
                default_lib = "/home/resolve/libs/Fusion/fusionscript.so"

    os.environ.setdefault("RESOLVE_SCRIPT_API", default_api)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", default_lib)

    modules_path = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
    if modules_path not in sys.path:
        sys.path.append(modules_path)


def get_resolve():
    """Return the top-level ``Resolve`` scripting object, or raise."""

    # Inside Resolve's own Python console / Scripts menu, `bmd` is already
    # a global builtin -- prefer that when available.
    bmd = sys.modules.get("__main__").__dict__.get("bmd") if "__main__" in sys.modules else None
    if bmd is not None:
        resolve = bmd.scriptapp("Resolve")
        if resolve is not None:
            return resolve

    _ensure_env_paths()

    try:
        import DaVinciResolveScript as dvr_script  # noqa: N813
    except ImportError as exc:
        raise ResolveConnectionError(
            "Could not import DaVinciResolveScript. Make sure DaVinci Resolve is "
            "installed and running, and that RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB "
            "point at your install (see README.md)."
        ) from exc

    resolve = dvr_script.scriptapp("Resolve")
    if resolve is None:
        raise ResolveConnectionError(
            "DaVinciResolveScript imported but returned no Resolve app instance. "
            "Is DaVinci Resolve running, and is external scripting enabled in "
            "Preferences > System > General?"
        )
    return resolve


def get_project_and_timeline(resolve):
    """Return ``(project, timeline, media_pool)`` for the currently open project."""

    project_manager = resolve.GetProjectManager()
    if project_manager is None:
        raise ResolveConnectionError("GetProjectManager() returned None.")

    project = project_manager.GetCurrentProject()
    if project is None:
        raise ResolveConnectionError("No project is currently open in Resolve.")

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise ResolveConnectionError(
            "No timeline is currently open. Open/select a timeline in the Edit page first."
        )

    media_pool = project.GetMediaPool()
    if media_pool is None:
        raise ResolveConnectionError("GetMediaPool() returned None.")

    return project, timeline, media_pool
