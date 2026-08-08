"""Export manual captions as an FCP7 XML v5 sequence: the source video on
a single video/audio track, with one sequence marker per caption (named
with the caption text) so line-up in DaVinci Resolve's timeline. This is a
lighter-weight interchange than generator/title clips -- Resolve reads
sequence markers natively and they're trivial to convert into subtitles
or line up cuts against.
"""

import os
from typing import List, Tuple
from xml.dom import minidom
import xml.etree.ElementTree as ET

from silence_cut_app.fcp7_xml import _add_rate, fps_to_timebase, path_to_pathurl

from create_text_app.subtitles import Segment

_MARKER_NAME_MAX_LEN = 60


def _marker_name(text: str) -> str:
    text = " ".join(text.split())  # collapse newlines/repeated whitespace
    if len(text) <= _MARKER_NAME_MAX_LEN:
        return text
    return text[: _MARKER_NAME_MAX_LEN - 1].rstrip() + "…"


def build_marker_xml(
    sequence_name: str,
    fps: float,
    video_path: str,
    video_duration_sec: float,
    segments: List[Segment],
    dimensions: Tuple[int, int] = (1920, 1080),
) -> str:
    """Build an FCP7 XML v5 document: the source video placed whole on a
    single video/audio track, plus one sequence marker per non-empty
    caption ``segments`` entry (positioned at its start time, spanning its
    start-to-end range).
    """

    timebase, ntsc = fps_to_timebase(fps)
    total_frames = round(video_duration_sec * fps)
    width, height = dimensions

    xmeml = ET.Element("xmeml", {"version": "5"})
    sequence = ET.SubElement(xmeml, "sequence")
    ET.SubElement(sequence, "name").text = sequence_name
    ET.SubElement(sequence, "duration").text = str(total_frames)
    _add_rate(sequence, timebase, ntsc)

    media = ET.SubElement(sequence, "media")
    video_el = ET.SubElement(media, "video")
    video_format = ET.SubElement(video_el, "format")
    samplechar = ET.SubElement(video_format, "samplecharacteristics")
    ET.SubElement(samplechar, "width").text = str(width)
    ET.SubElement(samplechar, "height").text = str(height)

    v_track = ET.SubElement(video_el, "track")
    audio_el = ET.SubElement(media, "audio")
    a_track = ET.SubElement(audio_el, "track")

    file_id = "file-1"
    for track, tag in ((v_track, "v"), (a_track, "a")):
        clipitem = ET.SubElement(track, "clipitem", {"id": f"clipitem-{tag}1-1"})
        ET.SubElement(clipitem, "name").text = os.path.basename(video_path)
        ET.SubElement(clipitem, "duration").text = str(total_frames)
        _add_rate(clipitem, timebase, ntsc)
        ET.SubElement(clipitem, "start").text = "0"
        ET.SubElement(clipitem, "end").text = str(total_frames)
        ET.SubElement(clipitem, "in").text = "0"
        ET.SubElement(clipitem, "out").text = str(total_frames)

        if tag == "v":
            file_el = ET.SubElement(clipitem, "file", {"id": file_id})
            ET.SubElement(file_el, "name").text = os.path.basename(video_path)
            ET.SubElement(file_el, "pathurl").text = path_to_pathurl(video_path)
            _add_rate(file_el, timebase, ntsc)
            file_media = ET.SubElement(file_el, "media")
            file_video = ET.SubElement(file_media, "video")
            file_samplechar = ET.SubElement(file_video, "samplecharacteristics")
            ET.SubElement(file_samplechar, "width").text = str(width)
            ET.SubElement(file_samplechar, "height").text = str(height)
            ET.SubElement(file_media, "audio")
        else:
            ET.SubElement(clipitem, "file", {"id": file_id})

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        marker = ET.SubElement(sequence, "marker")
        ET.SubElement(marker, "name").text = _marker_name(text)
        ET.SubElement(marker, "comment").text = text
        in_frame = round(seg.start * fps)
        out_frame = round(seg.end * fps)
        ET.SubElement(marker, "in").text = str(in_frame)
        ET.SubElement(marker, "out").text = str(out_frame) if out_frame > in_frame else "-1"

    rough = ET.tostring(xmeml, encoding="unicode")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ")
    body = pretty.split("?>", 1)[1].lstrip("\n")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body


def write_marker_xml(path: str, sequence_name: str, fps: float, video_path: str, video_duration_sec: float, segments: List[Segment], **kwargs) -> None:
    xml_str = build_marker_xml(sequence_name, fps, video_path, video_duration_sec, segments, **kwargs)
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml_str)
