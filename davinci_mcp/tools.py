"""Resolve operations exposed to Claude Code as MCP tools.

Every function here returns plain JSON-able data (dicts/lists/str) so the
MCP layer in ``server.py`` can hand results straight back to the model.
Kept separate from ``server.py`` so it's importable and unit-testable
without the ``mcp`` package or a real Resolve install -- tests swap
``get_resolve`` for a fake.

Like the rest of the Resolve-facing code in this repo, the API calls here
follow Blackmagic's scripting README and have not been execution-tested
against a real Resolve instance.

IMPORTANT: the MCP stdio transport uses this process's stdout for the
protocol itself, so anything that might ``print`` (davinci_auto_cut.run
does) is wrapped in ``_captured_stdout`` and its output is returned as
part of the tool result instead.
"""

import contextlib
import io
import os
from typing import List, Optional

from davinci_auto_cut import resolve_connect
from davinci_auto_cut.config import AutoCutConfig
from davinci_auto_cut.timeline_items import get_timeline_fps

PAGES = ("media", "cut", "edit", "fusion", "color", "fairlight", "deliver")

MARKER_COLORS = (
    "Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia",
    "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream",
)


class ToolError(RuntimeError):
    pass


def get_resolve():
    """Indirection point so tests can substitute a fake Resolve."""
    return resolve_connect.get_resolve()


@contextlib.contextmanager
def _captured_stdout():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


def _project(resolve):
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        raise ToolError("No project is currently open in Resolve.")
    return project


def _timeline(project):
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise ToolError("No timeline is currently open. Open one in the Edit page first.")
    return timeline


def _timelines(project):
    return [project.GetTimelineByIndex(i) for i in range(1, (project.GetTimelineCount() or 0) + 1)]


# --------------------------------------------------------------------------
# Status / navigation
# --------------------------------------------------------------------------

def get_status() -> dict:
    """Resolve version, current page, open project and timeline."""

    resolve = get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline() if project else None
    return {
        "product": resolve.GetProductName(),
        "version": resolve.GetVersionString(),
        "page": resolve.GetCurrentPage(),
        "project": project.GetName() if project else None,
        "timeline": timeline.GetName() if timeline else None,
        "timeline_count": (project.GetTimelineCount() or 0) if project else 0,
    }


def open_page(page: str) -> dict:
    """Switch Resolve to a page: media, cut, edit, fusion, color, fairlight or deliver."""

    page = page.lower()
    if page not in PAGES:
        raise ToolError(f"Unknown page {page!r}. Choose one of: {', '.join(PAGES)}")
    ok = get_resolve().OpenPage(page)
    return {"ok": bool(ok), "page": page}


# --------------------------------------------------------------------------
# Timelines
# --------------------------------------------------------------------------

def list_timelines() -> List[dict]:
    """List the project's timelines (name, fps, frame range, which one is current)."""

    project = _project(get_resolve())
    current = project.GetCurrentTimeline()
    current_name = current.GetName() if current else None
    return [
        {
            "index": i,
            "name": tl.GetName(),
            "current": tl.GetName() == current_name,
            "fps": get_timeline_fps(tl),
            "start_frame": tl.GetStartFrame(),
            "end_frame": tl.GetEndFrame(),
        }
        for i, tl in enumerate(_timelines(project), start=1)
    ]


def set_current_timeline(name: str) -> dict:
    """Make the timeline called ``name`` the current one."""

    project = _project(get_resolve())
    for tl in _timelines(project):
        if tl.GetName() == name:
            return {"ok": bool(project.SetCurrentTimeline(tl)), "timeline": name}
    raise ToolError(f"No timeline named {name!r}.")


def create_timeline(name: str) -> dict:
    """Create an empty timeline called ``name`` and make it current."""

    project = _project(get_resolve())
    timeline = project.GetMediaPool().CreateEmptyTimeline(name)
    if timeline is None:
        raise ToolError(f"Resolve refused to create timeline {name!r} (name already used?).")
    project.SetCurrentTimeline(timeline)
    return {"ok": True, "timeline": timeline.GetName()}


def get_timeline_items(track_type: str = "video", track_index: Optional[int] = None) -> List[dict]:
    """List clips on the current timeline. ``track_index=None`` means all
    tracks of ``track_type`` ("video", "audio" or "subtitle").
    """

    if track_type not in ("video", "audio", "subtitle"):
        raise ToolError("track_type must be 'video', 'audio' or 'subtitle'.")

    timeline = _timeline(_project(get_resolve()))
    fps = get_timeline_fps(timeline)
    start = timeline.GetStartFrame()

    indices = [track_index] if track_index else range(1, (timeline.GetTrackCount(track_type) or 0) + 1)
    items = []
    for idx in indices:
        for item in timeline.GetItemListInTrack(track_type, idx) or []:
            mpi = item.GetMediaPoolItem()
            items.append(
                {
                    "track": idx,
                    "name": item.GetName(),
                    "start_frame": item.GetStart(),
                    "end_frame": item.GetEnd(),
                    "start_sec": round((item.GetStart() - start) / fps, 3),
                    "duration_sec": round(item.GetDuration() / fps, 3),
                    "file_path": (mpi.GetClipProperty("File Path") or None) if mpi else None,
                }
            )
    items.sort(key=lambda d: (d["track"], d["start_frame"]))
    return items


# --------------------------------------------------------------------------
# Markers
# --------------------------------------------------------------------------

def add_marker(
    seconds: float,
    name: str = "",
    note: str = "",
    color: str = "Blue",
    duration_sec: float = 0.0,
) -> dict:
    """Add a marker ``seconds`` after the start of the current timeline."""

    color = color.capitalize()
    if color not in MARKER_COLORS:
        raise ToolError(f"Unknown marker color {color!r}. Choose one of: {', '.join(MARKER_COLORS)}")

    timeline = _timeline(_project(get_resolve()))
    fps = get_timeline_fps(timeline)
    frame = round(seconds * fps)  # AddMarker frames are relative to the timeline start
    duration = max(1, round(duration_sec * fps))
    ok = timeline.AddMarker(frame, color, name, note, duration)
    if not ok:
        raise ToolError(f"Resolve rejected the marker at frame {frame} (one may already exist there).")
    return {"ok": True, "frame": frame, "seconds": seconds}


def get_markers() -> List[dict]:
    """List markers on the current timeline (seconds from timeline start)."""

    timeline = _timeline(_project(get_resolve()))
    fps = get_timeline_fps(timeline)
    markers = timeline.GetMarkers() or {}
    return [
        {
            "frame": int(frame),
            "seconds": round(float(frame) / fps, 3),
            "color": info.get("color"),
            "name": info.get("name"),
            "note": info.get("note"),
            "duration_sec": round(info.get("duration", 1) / fps, 3),
        }
        for frame, info in sorted(markers.items(), key=lambda kv: float(kv[0]))
    ]


def delete_markers(color: str = "All") -> dict:
    """Delete markers of one color from the current timeline, or all with "All"."""

    color = "All" if color.lower() == "all" else color.capitalize()
    timeline = _timeline(_project(get_resolve()))
    return {"ok": bool(timeline.DeleteMarkersByColor(color)), "color": color}


# --------------------------------------------------------------------------
# Media pool
# --------------------------------------------------------------------------

def _walk_folder(folder, path=""):
    here = f"{path}/{folder.GetName()}" if path else folder.GetName()
    for clip in folder.GetClipList() or []:
        yield here, clip
    for sub in folder.GetSubFolderList() or []:
        yield from _walk_folder(sub, here)


def list_media_pool() -> List[dict]:
    """List every clip in the media pool, including sub-folders."""

    media_pool = _project(get_resolve()).GetMediaPool()
    return [
        {
            "folder": folder,
            "name": clip.GetName(),
            "file_path": clip.GetClipProperty("File Path") or None,
            "duration": clip.GetClipProperty("Duration") or None,
            "fps": clip.GetClipProperty("FPS") or None,
        }
        for folder, clip in _walk_folder(media_pool.GetRootFolder())
    ]


def import_media(file_paths: List[str]) -> dict:
    """Import files (absolute paths) into the current media pool folder."""

    missing = [p for p in file_paths if not os.path.exists(p)]
    if missing:
        raise ToolError(f"File(s) not found: {', '.join(missing)}")
    media_pool = _project(get_resolve()).GetMediaPool()
    items = media_pool.ImportMedia(list(file_paths)) or []
    return {"imported": [item.GetName() for item in items]}


def append_to_timeline(clip_names: List[str]) -> dict:
    """Append media-pool clips (by name, in the given order) to the end of
    the current timeline -- or a new one if the project has none open.
    """

    media_pool = _project(get_resolve()).GetMediaPool()
    by_name = {}
    for _folder, clip in _walk_folder(media_pool.GetRootFolder()):
        by_name.setdefault(clip.GetName(), clip)

    missing = [n for n in clip_names if n not in by_name]
    if missing:
        raise ToolError(f"Not in the media pool: {', '.join(missing)}")

    appended = media_pool.AppendToTimeline([by_name[n] for n in clip_names]) or []
    return {"appended": len(appended)}


# --------------------------------------------------------------------------
# Auto cut (silence / filler words) -- reuses davinci_auto_cut.run
# --------------------------------------------------------------------------

def auto_cut(
    source_files: Optional[List[str]] = None,
    apply: bool = False,
    track: int = 1,
    silence_threshold_db: float = -35.0,
    min_silence_duration: float = 0.4,
    filler_words: bool = False,
    language: str = "ja-JP",
    padding: float = 0.08,
    min_keep_duration: float = 0.15,
) -> dict:
    """Cut silence (and optionally filler words) -- same as
    ``python -m davinci_auto_cut.run``.

    With ``source_files``: analyze those files and build the cut result onto
    the current (or a new) timeline. Without: cut the clips already on video
    track ``track`` of the current timeline. ``apply=False`` (default) is a
    dry run -- file mode only reports, timeline mode adds red markers at
    planned cuts. ``filler_words=True`` uses Google Cloud Speech-to-Text
    (billed; needs GOOGLE_APPLICATION_CREDENTIALS).
    """

    from davinci_auto_cut import run  # heavy-ish, import lazily

    config = AutoCutConfig(
        target_video_track=track,
        silence_threshold_db=silence_threshold_db,
        min_silence_duration=min_silence_duration,
        enable_filler_word_removal=filler_words,
        google_language_code=language,
        padding=padding,
        min_keep_duration=min_keep_duration,
        dry_run=not apply,
    )
    resolve = get_resolve()
    with _captured_stdout() as out:
        if source_files:
            run.run_file_mode(config, source_files, resolve)
        else:
            run.run_timeline_mode(config, resolve)
    return {"applied": apply, "log": out.getvalue()}


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def list_render_presets() -> List[str]:
    """List render preset names usable with ``render``."""

    return list(_project(get_resolve()).GetRenderPresetList() or [])


def render(preset: str, target_dir: str, custom_name: Optional[str] = None, start: bool = True) -> dict:
    """Queue the current timeline with ``preset`` and (by default) start it."""

    project = _project(get_resolve())
    _timeline(project)
    if not project.LoadRenderPreset(preset):
        raise ToolError(f"Unknown render preset {preset!r}. Use list_render_presets to see valid names.")

    settings = {"TargetDir": os.path.expanduser(target_dir)}
    if custom_name:
        settings["CustomName"] = custom_name
    if not project.SetRenderSettings(settings):
        raise ToolError(f"Resolve rejected render settings {settings!r}.")

    job_id = project.AddRenderJob()
    if not job_id:
        raise ToolError("Resolve refused to add the render job.")
    started = bool(project.StartRendering(job_id)) if start else False
    return {"job_id": job_id, "started": started}


def render_status(job_id: str) -> dict:
    """Progress/status of a render job started with ``render``."""

    project = _project(get_resolve())
    status = project.GetRenderJobStatus(job_id) or {}
    return {"job_id": job_id, "rendering": bool(project.IsRenderingInProgress()), **status}
