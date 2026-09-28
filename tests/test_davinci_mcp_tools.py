"""davinci_mcp.tools against a fake in-memory Resolve (no real Resolve here)."""

import pytest

from davinci_mcp import tools


class FakeClip:
    def __init__(self, name, path):
        self.name, self.path = name, path

    def GetName(self):
        return self.name

    def GetClipProperty(self, key):
        return {"File Path": self.path, "Duration": "00:00:10:00", "FPS": "25"}.get(key)


class FakeFolder:
    def __init__(self, name, clips=(), subs=()):
        self.name, self.clips, self.subs = name, list(clips), list(subs)

    def GetName(self):
        return self.name

    def GetClipList(self):
        return self.clips

    def GetSubFolderList(self):
        return self.subs


class FakeItem:
    def __init__(self, name, start, end, clip):
        self.name, self.start, self.end, self.clip = name, start, end, clip

    def GetName(self):
        return self.name

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetDuration(self):
        return self.end - self.start

    def GetMediaPoolItem(self):
        return self.clip


class FakeTimeline:
    def __init__(self, name, items=()):
        self.name, self.items, self.markers = name, list(items), {}

    def GetName(self):
        return self.name

    def GetSetting(self, key):
        return "25" if key == "timelineFrameRate" else None

    def GetStartFrame(self):
        return 90000

    def GetEndFrame(self):
        return 90500

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, idx):
        return self.items if (track_type, idx) == ("video", 1) else []

    def AddMarker(self, frame, color, name, note, duration):
        if frame in self.markers:
            return False
        self.markers[frame] = {"color": color, "name": name, "note": note, "duration": duration}
        return True

    def GetMarkers(self):
        return dict(self.markers)

    def DeleteMarkersByColor(self, color):
        self.markers = {f: m for f, m in self.markers.items() if color != "All" and m["color"] != color}
        return True


class FakeMediaPool:
    def __init__(self, project, root):
        self.project, self.root, self.appended = project, root, []

    def GetRootFolder(self):
        return self.root

    def ImportMedia(self, paths):
        clips = [FakeClip(p.rsplit("/", 1)[-1], p) for p in paths]
        self.root.clips.extend(clips)
        return clips

    def AppendToTimeline(self, clips):
        self.appended.extend(clips)
        return clips

    def CreateEmptyTimeline(self, name):
        if any(t.GetName() == name for t in self.project.timelines):
            return None
        tl = FakeTimeline(name)
        self.project.timelines.append(tl)
        return tl


class FakeProject:
    def __init__(self):
        clip = FakeClip("a.mp4", "/media/a.mp4")
        self.timelines = [FakeTimeline("Main", [FakeItem("a.mp4", 90050, 90300, clip)])]
        self.current = self.timelines[0]
        self.media_pool = FakeMediaPool(self, FakeFolder("Master", [clip], [FakeFolder("B-roll", [FakeClip("b.mov", "/media/b.mov")])]))
        self.render_settings = None

    def GetName(self):
        return "Demo"

    def GetCurrentTimeline(self):
        return self.current

    def SetCurrentTimeline(self, tl):
        self.current = tl
        return True

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, i):
        return self.timelines[i - 1]

    def GetMediaPool(self):
        return self.media_pool

    def GetRenderPresetList(self):
        return ["YouTube - 1080p", "H.264 Master"]

    def LoadRenderPreset(self, name):
        return name in self.GetRenderPresetList()

    def SetRenderSettings(self, settings):
        self.render_settings = settings
        return True

    def AddRenderJob(self):
        return "job-1"

    def StartRendering(self, job_id):
        return True

    def IsRenderingInProgress(self):
        return True

    def GetRenderJobStatus(self, job_id):
        return {"JobStatus": "Rendering", "CompletionPercentage": 42}


class FakeResolve:
    def __init__(self):
        self.project, self.page = FakeProject(), "edit"

    def GetProjectManager(self):
        resolve = self

        class PM:
            def GetCurrentProject(self):
                return resolve.project

        return PM()

    def GetProductName(self):
        return "DaVinci Resolve Studio"

    def GetVersionString(self):
        return "20.0.0"

    def GetCurrentPage(self):
        return self.page

    def OpenPage(self, page):
        self.page = page
        return True


@pytest.fixture
def resolve(monkeypatch):
    fake = FakeResolve()
    monkeypatch.setattr(tools, "get_resolve", lambda: fake)
    return fake


def test_status(resolve):
    assert tools.get_status() == {
        "product": "DaVinci Resolve Studio", "version": "20.0.0", "page": "edit",
        "project": "Demo", "timeline": "Main", "timeline_count": 1,
    }


def test_open_page_validates(resolve):
    assert tools.open_page("Color") == {"ok": True, "page": "color"}
    with pytest.raises(tools.ToolError):
        tools.open_page("nope")


def test_timelines_create_and_switch(resolve):
    tools.create_timeline("Cut 2")
    names = [(t["name"], t["current"]) for t in tools.list_timelines()]
    assert names == [("Main", False), ("Cut 2", True)]
    tools.set_current_timeline("Main")
    assert tools.get_status()["timeline"] == "Main"
    with pytest.raises(tools.ToolError):
        tools.create_timeline("Main")
    with pytest.raises(tools.ToolError):
        tools.set_current_timeline("missing")


def test_timeline_items_seconds_relative_to_timeline_start(resolve):
    [item] = tools.get_timeline_items()
    assert item["start_sec"] == 2.0  # (90050 - 90000) / 25
    assert item["duration_sec"] == 10.0
    assert item["file_path"] == "/media/a.mp4"


def test_markers_roundtrip(resolve):
    assert tools.add_marker(4.0, name="Intro", color="red", duration_sec=1.0)["frame"] == 100
    with pytest.raises(tools.ToolError):
        tools.add_marker(4.0)  # same frame twice
    [m] = tools.get_markers()
    assert (m["seconds"], m["color"], m["name"], m["duration_sec"]) == (4.0, "Red", "Intro", 1.0)
    tools.delete_markers("all")
    assert tools.get_markers() == []


def test_marker_color_validated(resolve):
    with pytest.raises(tools.ToolError):
        tools.add_marker(1.0, color="orange")


def test_media_pool_walks_subfolders(resolve):
    assert [(c["folder"], c["name"]) for c in tools.list_media_pool()] == [
        ("Master", "a.mp4"), ("Master/B-roll", "b.mov"),
    ]


def test_import_and_append(resolve, tmp_path):
    f = tmp_path / "c.mp4"
    f.write_bytes(b"")
    assert tools.import_media([str(f)]) == {"imported": ["c.mp4"]}
    assert tools.append_to_timeline(["b.mov", "c.mp4"]) == {"appended": 2}
    with pytest.raises(tools.ToolError):
        tools.append_to_timeline(["nope.mp4"])
    with pytest.raises(tools.ToolError):
        tools.import_media([str(tmp_path / "missing.mp4")])


def test_render(resolve):
    assert tools.render("YouTube - 1080p", "/out", custom_name="final") == {"job_id": "job-1", "started": True}
    assert resolve.project.render_settings == {"TargetDir": "/out", "CustomName": "final"}
    assert tools.render_status("job-1")["CompletionPercentage"] == 42
    with pytest.raises(tools.ToolError):
        tools.render("Nope", "/out")


def test_auto_cut_captures_prints(resolve, monkeypatch, capsys):
    from davinci_auto_cut import run

    def fake_timeline_mode(config, _resolve):
        assert config.dry_run and config.target_video_track == 2
        print("Planned cuts: 3")

    monkeypatch.setattr(run, "run_timeline_mode", fake_timeline_mode)
    result = tools.auto_cut(track=2)
    assert result == {"applied": False, "log": "Planned cuts: 3\n"}
    assert capsys.readouterr().out == ""  # nothing leaked onto the MCP stdio stream
