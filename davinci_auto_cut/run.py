"""Entry point: detect silence/filler words and cut them out.

Two modes, chosen by whether ``--source-files`` is given:

1. File mode (``--source-files a.mp4 b.mp4 ...``): analyze video files on
   disk and build a *new* Resolve timeline from the kept segments, in the
   order the files were given. Nothing existing in the project is
   touched -- this only imports media and appends to (or creates) a
   timeline.

2. Timeline mode (no ``--source-files``): analyze clips already sitting
   on the current timeline's video track and, when ``--apply`` is passed,
   rebuild that track with the cuts applied. Defaults to a dry run that
   only adds preview markers.

Run this from Resolve's Workspace > Scripts menu (after running
install.py), from Resolve's Console, or as an external process:

    python -m davinci_auto_cut.run --source-files interview.mp4 --filler-words --apply

This has not been execution-tested against a real Resolve instance --
see README.md "Testing notes" before running it on anything you can't
afford to redo.
"""

import argparse
import os
import sys

from davinci_auto_cut.audio_extract import extract_audio_segment
from davinci_auto_cut.config import AutoCutConfig
from davinci_auto_cut.cutlist import complement_intervals, intervals_to_keep_segments
from davinci_auto_cut.editor import add_cut_markers, apply_all_cuts
from davinci_auto_cut.ffprobe import probe_duration
from davinci_auto_cut.filler_words import find_filler_intervals
from davinci_auto_cut.media_import import append_files_to_timeline
from davinci_auto_cut.resolve_connect import ResolveConnectionError, get_project_and_timeline, get_resolve
from davinci_auto_cut.silence import detect_silence
from davinci_auto_cut.timeline_items import get_video_items


def parse_args(argv=None) -> AutoCutConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-files", nargs="+", default=None,
                         help="Video file(s) on disk to cut and place on a new/current timeline.")
    parser.add_argument("--track", type=int, default=1, help="Video track index (timeline mode only).")
    parser.add_argument("--apply", action="store_true", help="Actually perform the edit (default: dry run).")
    parser.add_argument("--no-silence", action="store_true", help="Disable silence-based cutting.")
    parser.add_argument("--silence-threshold-db", type=float, default=-35.0)
    parser.add_argument("--min-silence-duration", type=float, default=0.4)
    parser.add_argument("--filler-words", action="store_true", help="Enable Google STT filler-word removal.")
    parser.add_argument("--language", default="ja-JP", help="BCP-47 language code for Google STT.")
    parser.add_argument("--padding", type=float, default=0.08)
    parser.add_argument("--min-keep-duration", type=float, default=0.15)

    args, _unknown = parser.parse_known_args(argv)

    config = AutoCutConfig(
        target_video_track=args.track,
        enable_silence_cut=not args.no_silence,
        silence_threshold_db=args.silence_threshold_db,
        min_silence_duration=args.min_silence_duration,
        enable_filler_word_removal=args.filler_words,
        google_language_code=args.language,
        padding=args.padding,
        min_keep_duration=args.min_keep_duration,
        dry_run=not args.apply,
    )
    return config, args.source_files


def _detect_cut_intervals(config: AutoCutConfig, wav_path: str, duration_sec: float):
    cut_intervals = []

    if config.enable_silence_cut:
        cut_intervals += detect_silence(wav_path, config.silence_threshold_db, config.min_silence_duration)

    if config.enable_filler_word_removal:
        from davinci_auto_cut.google_stt import transcribe_words  # optional dep, import lazily

        words = transcribe_words(
            wav_path,
            duration_sec,
            language_code=config.google_language_code,
            chunk_seconds=config.google_chunk_seconds,
            temp_dir=config.temp_dir,
        )
        cut_intervals += find_filler_intervals(words, config.filler_words)

    return cut_intervals


def run_file_mode(config: AutoCutConfig, source_files, resolve) -> None:
    _project, _timeline, media_pool = get_project_and_timeline_optional(resolve)

    files_with_keep_segments = []
    report = []

    for file_path in source_files:
        if not os.path.isfile(file_path):
            print(f"[skip] not a file: {file_path}", file=sys.stderr)
            continue

        duration_sec = probe_duration(file_path)
        wav_path = extract_audio_segment(file_path, 0.0, duration_sec, config.sample_rate, config.temp_dir)
        try:
            cut_intervals = _detect_cut_intervals(config, wav_path, duration_sec)
        finally:
            os.remove(wav_path)

        keep_segments = intervals_to_keep_segments(
            duration_sec, cut_intervals, config.padding, config.min_keep_duration
        )
        actual_cuts = complement_intervals(keep_segments, duration_sec)
        removed_sec = sum(e - s for s, e in actual_cuts)

        report.append((file_path, duration_sec, removed_sec, len(actual_cuts)))
        files_with_keep_segments.append((file_path, keep_segments))

    total_removed = sum(r[2] for r in report)
    print("Planned cuts:")
    for file_path, duration_sec, removed_sec, n_cuts in report:
        print(f"  {file_path}: {n_cuts} cut(s), removing {removed_sec:.1f}s of {duration_sec:.1f}s")
    print(f"Total removed: {total_removed:.1f}s")

    if config.dry_run:
        print("[dry-run] No changes made. Re-run with --apply to import and build the timeline.")
        return

    if media_pool is None:
        raise ResolveConnectionError("No MediaPool available to import into.")

    applied = append_files_to_timeline(media_pool, files_with_keep_segments)
    print(f"Built timeline with {len(applied)} segment(s) from {len(files_with_keep_segments)} file(s).")


def run_timeline_mode(config: AutoCutConfig, resolve) -> None:
    _project, timeline, media_pool = get_project_and_timeline(resolve)

    clips = get_video_items(timeline, config.target_video_track)
    if not clips:
        print(f"No clips found on video track {config.target_video_track}.")
        return

    results = []
    for clip in clips:
        if not clip.file_path:
            print(f"[skip] {clip.name}: no source file path", file=sys.stderr)
            continue

        wav_path = extract_audio_segment(
            clip.file_path, clip.source_start_sec, clip.source_duration_sec, config.sample_rate, config.temp_dir
        )
        try:
            cut_intervals = _detect_cut_intervals(config, wav_path, clip.source_duration_sec)
        finally:
            os.remove(wav_path)

        keep_segments = intervals_to_keep_segments(
            clip.source_duration_sec, cut_intervals, config.padding, config.min_keep_duration
        )
        actual_cuts = complement_intervals(keep_segments, clip.source_duration_sec)
        results.append((clip, keep_segments, actual_cuts))

    total_removed = sum(sum(e - s for s, e in cuts) for _, _, cuts in results)
    total_cuts = sum(len(cuts) for _, _, cuts in results)
    print(f"Planned cuts: {total_cuts} across {len(results)} clip(s), removing ~{total_removed:.1f}s.")

    if config.dry_run:
        total_markers = sum(add_cut_markers(timeline, clip, cuts) for clip, _, cuts in results)
        print(f"[dry-run] Added {total_markers} marker(s). Review them, then re-run with --apply.")
        return

    clips_with_keep = [(clip, keep) for clip, keep, _ in results]
    applied = apply_all_cuts(media_pool, timeline, clips_with_keep)
    print(f"Applied cuts: rebuilt {len(clips_with_keep)} clip(s) into {len(applied)} segment(s).")


def get_project_and_timeline_optional(resolve):
    """Like resolve_connect.get_project_and_timeline, but tolerates there
    being no current timeline yet -- file mode is allowed to create one.
    """

    project_manager = resolve.GetProjectManager()
    if project_manager is None:
        raise ResolveConnectionError("GetProjectManager() returned None.")

    project = project_manager.GetCurrentProject()
    if project is None:
        raise ResolveConnectionError("No project is currently open in Resolve.")

    timeline = project.GetCurrentTimeline()  # may legitimately be None here
    media_pool = project.GetMediaPool()
    if media_pool is None:
        raise ResolveConnectionError("GetMediaPool() returned None.")

    return project, timeline, media_pool


def main(argv=None) -> int:
    config, source_files = parse_args(argv)

    try:
        resolve = get_resolve()
    except ResolveConnectionError as exc:
        print(f"Could not connect to DaVinci Resolve: {exc}", file=sys.stderr)
        return 1

    try:
        if source_files:
            run_file_mode(config, source_files, resolve)
        else:
            run_timeline_mode(config, resolve)
    except ResolveConnectionError as exc:
        print(f"Resolve error: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
