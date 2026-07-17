"""Read/write a subset of the Final Cut Pro 7 XML Interchange Format (xmeml v5).

This is not a general-purpose FCP XML library -- it only handles the shapes
this app actually produces or consumes:

* Reading: a single sequence with one video track holding clipitems placed
  back to back (a "rough cut" -- clips laid down in order, no transitions,
  no effects, no gaps). This is the common shape of a timeline you'd export
  right after dropping clips onto it and before doing any real editing.
* Writing: a single sequence with 1 or 2 video tracks (2 for the two-camera
  sync mode), each with a matching linked audio track, holding the kept
  segments placed back to back starting at frame 0.

Frame <-> seconds conversion always uses the sequence's own frame rate, on
the assumption that clips were captured at (or conformed to) that rate --
true for the rough-sequence-from-raw-files workflow this app targets.
"""

import os
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from xml.dom import minidom

# Standard NTSC drop-frame rates: e.g. a "30fps" sequence flagged NTSC is
# really 29.97fps (30000/1001), and so on for 24/60.
NTSC_RATES = {24: 24000 / 1001, 30: 30000 / 1001, 60: 60000 / 1001}


def timebase_to_fps(timebase: int, ntsc: bool) -> float:
    if ntsc and timebase in NTSC_RATES:
        return NTSC_RATES[timebase]
    return float(timebase)


def fps_to_timebase(fps: float) -> Tuple[int, bool]:
    """Inverse of ``timebase_to_fps``, picking the closest standard rate."""

    for tb, rate in NTSC_RATES.items():
        if abs(fps - rate) < 0.02:
            return tb, True
    return int(round(fps)), False


def path_to_pathurl(path: str) -> str:
    return "file://localhost" + urllib.parse.quote(os.path.abspath(path))


def pathurl_to_path(pathurl: str) -> str:
    parsed = urllib.parse.urlparse(pathurl)
    path = urllib.parse.unquote(parsed.path)
    # "file://localhost/Users/..." parses with netloc="localhost"; a plain
    # "file:///Users/..." parses with netloc="". Either way `.path` is right.
    return path


@dataclass
class SourceClip:
    """A clip to analyze: either a whole file passed in directly, or one
    clipitem's in/out range as read from an input XML.

    ``source_start_sec``/``source_duration_sec`` describe the portion of
    ``file_path`` this clip covers -- ``(0, full_duration)`` for a raw file,
    or the clipitem's own range when parsed from a sequence.
    """

    file_path: str
    source_start_sec: float = 0.0
    source_duration_sec: float = 0.0
    name: Optional[str] = None

    def __post_init__(self):
        if self.name is None:
            self.name = os.path.basename(self.file_path)


@dataclass
class PlacedClip:
    """One clip to write into an output track: an absolute ``[in_sec,
    out_sec)`` range of ``file_path``, placed immediately after the
    previous clip on its track (tracks accumulate independently).
    """

    file_path: str
    in_sec: float
    out_sec: float
    name: Optional[str] = None

    def __post_init__(self):
        if self.name is None:
            self.name = os.path.basename(self.file_path)


def parse_fcp7_sequence(xml_path: str) -> Tuple[float, List[SourceClip]]:
    """Parse a single-video-track FCP7 XML v5 rough sequence.

    Returns ``(fps, clips)`` with clips in timeline order. Only the first
    video track is read -- see module docstring for the supported shape.
    """

    tree = ET.parse(xml_path)
    root = tree.getroot()

    sequence = root.find(".//sequence")
    if sequence is None:
        raise ValueError(f"No <sequence> found in {xml_path!r}")

    rate_el = sequence.find("./rate")
    if rate_el is None:
        raise ValueError(f"No sequence <rate> found in {xml_path!r}")
    timebase = int(rate_el.findtext("timebase", "30"))
    ntsc = rate_el.findtext("ntsc", "FALSE").strip().upper() == "TRUE"
    fps = timebase_to_fps(timebase, ntsc)

    video_track = sequence.find("./media/video/track")
    if video_track is None:
        raise ValueError(f"No video track found in {xml_path!r}")

    # A file is only fully <file id="..."><pathurl>...</pathurl>...</file>
    # defined once; every other clipitem using it just references that id
    # via an empty <file id="..."/>. Build the id -> path map up front so
    # those references resolve instead of being silently skipped.
    file_paths_by_id = {}
    for file_el in root.iter("file"):
        pathurl = file_el.findtext("pathurl")
        file_id = file_el.get("id")
        if pathurl and file_id:
            file_paths_by_id[file_id] = pathurl_to_path(pathurl)

    clips: List[SourceClip] = []
    for clipitem in video_track.findall("./clipitem"):
        in_frames = int(clipitem.findtext("in", "0"))
        out_frames = int(clipitem.findtext("out", "0"))
        file_el = clipitem.find("./file")
        if file_el is None:
            continue
        pathurl = file_el.findtext("pathurl")
        if pathurl:
            file_path = pathurl_to_path(pathurl)
        else:
            file_path = file_paths_by_id.get(file_el.get("id"))
        if not file_path:
            continue
        name = clipitem.findtext("name") or file_el.findtext("name")

        clips.append(
            SourceClip(
                file_path=file_path,
                source_start_sec=in_frames / fps,
                source_duration_sec=(out_frames - in_frames) / fps,
                name=name,
            )
        )

    return fps, clips


def _add_rate(parent: ET.Element, timebase: int, ntsc: bool) -> None:
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(timebase)
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"


def _add_clipitem(
    track: ET.Element,
    clip_id: str,
    file_id: str,
    file_path: str,
    name: str,
    timebase: int,
    ntsc: bool,
    fps: float,
    timeline_start_frame: int,
    in_sec: float,
    out_sec: float,
    file_ids_defined: Dict[str, str],
    file_dimensions: Dict[str, Tuple[int, int]],
    default_dimensions: Tuple[int, int],
) -> int:
    """Append one ``<clipitem>`` to ``track``. Returns its duration in frames."""

    in_frames = round(in_sec * fps)
    out_frames = round(out_sec * fps)
    duration_frames = out_frames - in_frames

    clipitem = ET.SubElement(track, "clipitem", {"id": clip_id})
    ET.SubElement(clipitem, "name").text = name
    ET.SubElement(clipitem, "duration").text = str(duration_frames)
    _add_rate(clipitem, timebase, ntsc)
    ET.SubElement(clipitem, "start").text = str(timeline_start_frame)
    ET.SubElement(clipitem, "end").text = str(timeline_start_frame + duration_frames)
    ET.SubElement(clipitem, "in").text = str(in_frames)
    ET.SubElement(clipitem, "out").text = str(out_frames)

    if file_path in file_ids_defined:
        ET.SubElement(clipitem, "file", {"id": file_ids_defined[file_path]})
    else:
        file_ids_defined[file_path] = file_id
        width, height = file_dimensions.get(file_path, default_dimensions)

        file_el = ET.SubElement(clipitem, "file", {"id": file_id})
        ET.SubElement(file_el, "name").text = os.path.basename(file_path)
        ET.SubElement(file_el, "pathurl").text = path_to_pathurl(file_path)
        _add_rate(file_el, timebase, ntsc)
        media_el = ET.SubElement(file_el, "media")
        video_el = ET.SubElement(media_el, "video")
        samplechar = ET.SubElement(video_el, "samplecharacteristics")
        ET.SubElement(samplechar, "width").text = str(width)
        ET.SubElement(samplechar, "height").text = str(height)
        ET.SubElement(media_el, "audio")

    return duration_frames


def build_fcp7_xml(
    sequence_name: str,
    fps: float,
    video_tracks: List[List[PlacedClip]],
    file_dimensions: Optional[Dict[str, Tuple[int, int]]] = None,
    default_dimensions: Tuple[int, int] = (1920, 1080),
) -> str:
    """Build an FCP7 XML v5 document: one sequence, 1-2 video tracks (each
    with a matching linked audio track), and return it as an XML string.

    ``video_tracks`` is a list of tracks (1 for the normal single-track
    mode, 2 for two-camera sync); each track is its kept segments in
    timeline order, placed back to back starting at frame 0.
    """

    file_dimensions = file_dimensions or {}
    timebase, ntsc = fps_to_timebase(fps)

    xmeml = ET.Element("xmeml", {"version": "5"})
    sequence = ET.SubElement(xmeml, "sequence")
    ET.SubElement(sequence, "name").text = sequence_name

    total_frames = 0
    for track_clips in video_tracks:
        track_frames = sum(round(c.out_sec * fps) - round(c.in_sec * fps) for c in track_clips)
        total_frames = max(total_frames, track_frames)
    ET.SubElement(sequence, "duration").text = str(total_frames)
    _add_rate(sequence, timebase, ntsc)

    media = ET.SubElement(sequence, "media")
    video_el = ET.SubElement(media, "video")
    video_format = ET.SubElement(video_el, "format")
    samplechar = ET.SubElement(video_format, "samplecharacteristics")
    ET.SubElement(samplechar, "width").text = str(default_dimensions[0])
    ET.SubElement(samplechar, "height").text = str(default_dimensions[1])

    video_track_elements = [ET.SubElement(video_el, "track") for _ in video_tracks]

    audio_el = ET.SubElement(media, "audio")
    audio_track_elements = [ET.SubElement(audio_el, "track") for _ in video_tracks]

    file_ids_defined: Dict[str, str] = {}
    file_counter = 0
    clip_counter = 0

    for track_index, track_clips in enumerate(video_tracks):
        v_track_el = video_track_elements[track_index]
        a_track_el = audio_track_elements[track_index]
        timeline_frame = 0

        for clip in track_clips:
            if clip.file_path in file_ids_defined:
                file_id = file_ids_defined[clip.file_path]
            else:
                file_counter += 1
                file_id = f"file-{file_counter}"

            clip_counter += 1
            duration_frames = _add_clipitem(
                v_track_el,
                f"clipitem-v{track_index + 1}-{clip_counter}",
                file_id,
                clip.file_path,
                clip.name,
                timebase,
                ntsc,
                fps,
                timeline_frame,
                clip.in_sec,
                clip.out_sec,
                file_ids_defined,
                file_dimensions,
                default_dimensions,
            )
            _add_clipitem(
                a_track_el,
                f"clipitem-a{track_index + 1}-{clip_counter}",
                file_id,
                clip.file_path,
                clip.name,
                timebase,
                ntsc,
                fps,
                timeline_frame,
                clip.in_sec,
                clip.out_sec,
                file_ids_defined,
                file_dimensions,
                default_dimensions,
            )
            timeline_frame += duration_frames

    rough = ET.tostring(xmeml, encoding="unicode")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ")
    body = pretty.split("?>", 1)[1].lstrip("\n")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body


def write_fcp7_xml(path: str, sequence_name: str, fps: float, video_tracks, **kwargs) -> None:
    xml_str = build_fcp7_xml(sequence_name, fps, video_tracks, **kwargs)
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml_str)
