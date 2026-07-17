"""Orchestrates the silence auto-cut workflow: detect silence in one or more
clips, compute what to keep, and write the result out as an FCP7 XML v5
sequence -- either a single video track (files or an input XML) or two
synced video tracks (two-camera mode).
"""

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from davinci_auto_cut.audio_extract import extract_audio_segment
from davinci_auto_cut.cutlist import complement_intervals, intervals_to_keep_segments
from davinci_auto_cut.ffprobe import probe_dimensions, probe_duration, probe_fps
from davinci_auto_cut.silence import detect_silence

from silence_cut_app.fcp7_xml import PlacedClip, SourceClip, parse_fcp7_sequence, write_fcp7_xml
from silence_cut_app.intensity import get_settings
from silence_cut_app.sync import find_sync_offset

ProgressCallback = Optional[Callable[[str], None]]


@dataclass
class CutResult:
    fps: float
    total_input_sec: float
    total_output_sec: float
    num_cuts: int
    warnings: List[str] = field(default_factory=list)

    @property
    def removed_sec(self) -> float:
        return self.total_input_sec - self.total_output_sec


def _log(progress_cb: ProgressCallback, message: str) -> None:
    if progress_cb is not None:
        progress_cb(message)


def load_clips_from_files(file_paths: List[str]) -> Tuple[float, List[SourceClip]]:
    """Treat each file as one whole clip, in the given order."""

    if not file_paths:
        raise ValueError("no source files given")

    fps = probe_fps(file_paths[0])
    clips = [SourceClip(file_path=p, source_start_sec=0.0, source_duration_sec=probe_duration(p)) for p in file_paths]
    return fps, clips


def load_clips_from_xml(xml_path: str) -> Tuple[float, List[SourceClip]]:
    return parse_fcp7_sequence(xml_path)


def detect_keep_segments(
    file_path: str,
    range_start_sec: float,
    range_duration_sec: float,
    intensity,
    temp_dir: Optional[str] = None,
) -> List[Tuple[float, float]]:
    """Run silence detection over ``[range_start_sec, range_start_sec +
    range_duration_sec)`` of ``file_path`` and return the segments to keep,
    in coordinates local to that range (0 == range_start_sec).
    """

    settings = get_settings(intensity)

    wav_path = extract_audio_segment(file_path, range_start_sec, range_duration_sec, temp_dir=temp_dir)
    try:
        cut_intervals = detect_silence(wav_path, settings.silence_threshold_db, settings.min_silence_duration)
    finally:
        os.remove(wav_path)

    return intervals_to_keep_segments(range_duration_sec, cut_intervals, settings.padding, settings.min_keep_duration)


def _probe_file_dimensions(file_paths: List[str]) -> dict:
    dims = {}
    for path in file_paths:
        try:
            dims[path] = probe_dimensions(path)
        except Exception:
            pass
    return dims


def run_single_track(
    intensity,
    output_xml_path: str,
    source_files: Optional[List[str]] = None,
    xml_path: Optional[str] = None,
    sequence_name: str = "Silence Cut",
    temp_dir: Optional[str] = None,
    progress_cb: ProgressCallback = None,
) -> CutResult:
    """Single-video-track mode: cut silence out of raw video files (given in
    order) or an existing rough-sequence XML, and write a new FCP7 XML v5.
    """

    if bool(source_files) == bool(xml_path):
        raise ValueError("pass exactly one of source_files or xml_path")

    if xml_path:
        _log(progress_cb, f"XMLを読み込み中: {xml_path}")
        fps, clips = load_clips_from_xml(xml_path)
    else:
        _log(progress_cb, f"{len(source_files)}個の動画ファイルを解析中...")
        fps, clips = load_clips_from_files(source_files)

    total_input_sec = sum(c.source_duration_sec for c in clips)
    placed_clips: List[PlacedClip] = []

    for i, clip in enumerate(clips, start=1):
        _log(progress_cb, f"[{i}/{len(clips)}] {clip.name}: 無音を検出中...")
        keep_segments = detect_keep_segments(
            clip.file_path, clip.source_start_sec, clip.source_duration_sec, intensity, temp_dir
        )
        for local_start, local_end in keep_segments:
            placed_clips.append(
                PlacedClip(
                    file_path=clip.file_path,
                    in_sec=clip.source_start_sec + local_start,
                    out_sec=clip.source_start_sec + local_end,
                    name=clip.name,
                )
            )
        _log(progress_cb, f"[{i}/{len(clips)}] {clip.name}: {len(keep_segments)}個の区間を残す")

    total_output_sec = sum(c.out_sec - c.in_sec for c in placed_clips)

    _log(progress_cb, f"FCP7 XMLを書き出し中: {output_xml_path}")
    file_dimensions = _probe_file_dimensions(sorted({c.file_path for c in placed_clips}))
    write_fcp7_xml(output_xml_path, sequence_name, fps, [placed_clips], file_dimensions=file_dimensions)

    return CutResult(
        fps=fps,
        total_input_sec=total_input_sec,
        total_output_sec=total_output_sec,
        num_cuts=max(0, len(placed_clips) - len(clips)),
    )


def run_two_camera(
    cam1_path: str,
    cam2_path: str,
    intensity,
    output_xml_path: str,
    sequence_name: str = "Silence Cut (2cam)",
    analysis_window_sec: float = 300.0,
    temp_dir: Optional[str] = None,
    progress_cb: ProgressCallback = None,
) -> CutResult:
    """Two-camera mode: sync cam2 to cam1 via audio, detect silence on
    cam1's audio only, and apply the same cuts (offset-adjusted) to cam2 --
    producing a 2-video-track FCP7 XML v5 with matching timeline positions.
    """

    _log(progress_cb, "カメラ1の解像度・フレームレートを確認中...")
    fps = probe_fps(cam1_path)
    cam1_duration = probe_duration(cam1_path)
    cam2_duration = probe_duration(cam2_path)

    _log(progress_cb, "音声波形でカメラ1・カメラ2を同期中...")
    offset = find_sync_offset(cam1_path, cam2_path, analysis_window_sec=analysis_window_sec, temp_dir=temp_dir)
    _log(progress_cb, f"同期オフセット: {offset:+.3f}秒（カメラ2基準）")

    _log(progress_cb, "カメラ1の音声で無音を検出中...")
    keep_segments = detect_keep_segments(cam1_path, 0.0, cam1_duration, intensity, temp_dir)

    cam1_clips: List[PlacedClip] = []
    cam2_clips: List[PlacedClip] = []
    warnings: List[str] = []

    for start, end in keep_segments:
        cam1_clips.append(PlacedClip(cam1_path, start, end))

        # Force cam2's clip to the same frame duration as cam1's -- rounding
        # cam2's (offset-shifted) start/end to frames independently can land
        # on a different frame count than cam1's, which would desync the two
        # tracks' timeline positions by a frame. Only cam2's "in" point is
        # independently frame-rounded; "out" is derived from it so the two
        # tracks always advance in lockstep (as long as neither is clipped
        # below against cam2's own file bounds).
        duration_frames = round(end * fps) - round(start * fps)
        cam2_in_frames = round((start + offset) * fps)
        cam2_start = cam2_in_frames / fps
        cam2_end = (cam2_in_frames + duration_frames) / fps
        clipped_start = max(0.0, cam2_start)
        clipped_end = min(cam2_duration, cam2_end)

        if clipped_end <= clipped_start:
            warnings.append(
                f"カメラ1の {start:.2f}s-{end:.2f}s の区間はカメラ2の収録範囲外のため、"
                "カメラ2側のクリップを生成できませんでした。"
            )
            continue
        if clipped_start > cam2_start or clipped_end < cam2_end:
            warnings.append(
                f"カメラ1の {start:.2f}s-{end:.2f}s の区間はカメラ2の収録範囲を一部はみ出したため、"
                "カメラ2側では切り詰めています。"
            )
        cam2_clips.append(PlacedClip(cam2_path, clipped_start, clipped_end))

    total_input_sec = cam1_duration
    total_output_sec = sum(c.out_sec - c.in_sec for c in cam1_clips)

    _log(progress_cb, f"FCP7 XMLを書き出し中: {output_xml_path}")
    file_dimensions = _probe_file_dimensions([cam1_path, cam2_path])
    write_fcp7_xml(
        output_xml_path,
        sequence_name,
        fps,
        [cam1_clips, cam2_clips],
        file_dimensions=file_dimensions,
    )

    return CutResult(
        fps=fps,
        total_input_sec=total_input_sec,
        total_output_sec=total_output_sec,
        num_cuts=max(0, len(cam1_clips) - 1),
        warnings=warnings,
    )
