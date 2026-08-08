from create_text_app.manual_project import load_project, save_project
from create_text_app.subtitles import Segment


def test_save_then_load_round_trips(tmp_path):
    path = str(tmp_path / "project.json")
    segments = [
        Segment(start=1.0, end=2.5, text="hello"),
        Segment(start=5.0, end=6.0, text="world"),
    ]
    save_project(path, "/videos/cam.mp4", 29.97, 60.0, (1920, 1080), segments)

    loaded = load_project(path)

    assert loaded["video_path"] == "/videos/cam.mp4"
    assert loaded["fps"] == 29.97
    assert loaded["duration"] == 60.0
    assert loaded["dimensions"] == (1920, 1080)
    assert len(loaded["segments"]) == 2
    assert loaded["segments"][0].start == 1.0
    assert loaded["segments"][0].end == 2.5
    assert loaded["segments"][0].text == "hello"
    assert loaded["segments"][1].text == "world"


def test_load_handles_missing_optional_fields(tmp_path):
    path = tmp_path / "minimal.json"
    path.write_text('{"video_path": "/x.mp4", "segments": [{"start": 0, "end": 1, "text": "hi"}]}')

    loaded = load_project(str(path))

    assert loaded["video_path"] == "/x.mp4"
    assert loaded["fps"] == 30.0
    assert loaded["duration"] == 0.0
    assert loaded["dimensions"] == (1920, 1080)
    assert loaded["segments"][0].text == "hi"


def test_load_handles_empty_segments_list(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text('{"video_path": "/x.mp4", "fps": 25.0, "duration": 10.0, "dimensions": [640, 360], "segments": []}')

    loaded = load_project(str(path))

    assert loaded["segments"] == []
    assert loaded["fps"] == 25.0
    assert loaded["dimensions"] == (640, 360)
