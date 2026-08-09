"""Desktop GUI for Create Text.

Two modes, switchable at the top:

* 自動文字起こし (auto) -- local Whisper transcribes the whole file at once.
  Vrew-style editable segment list, no video preview (kept fast/light).
* 手動（音声入力） (manual) -- the user marks IN/OUT points on a scrub
  preview to lay down segments at exactly the length they want, then
  dictates each one into the mic; Whisper transcribes just that short clip.
  Exports to SRT or an FCP7 XML with one sequence marker per caption, for
  handoff into DaVinci Resolve.

Same black/purple dark theme as Auto Cut throughout.
"""

import os
import queue
import tempfile
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox

import customtkinter as ctk

from davinci_auto_cut.ffprobe import probe_dimensions, probe_duration, probe_fps
from silence_cut_app import theme
from silence_cut_app.intensity import INTENSITY_PRESETS, Intensity

from create_text_app import audio_playback, manual_transcribe, transcribe_engine
from create_text_app.audio_playback import AudioPlaybackError
from create_text_app.fcp7_markers import write_marker_xml
from create_text_app.manual_project import load_project, save_project
from create_text_app.mic_recorder import MicRecorder, MicRecorderError
from create_text_app.subtitles import Segment, build_srt, build_txt, build_vtt, parse_srt
from create_text_app.video_player import VideoFrameReader, VideoFrameReaderError

# Visual update rate during real-time playback. Deliberately well below the
# source video's own frame rate -- reading via a hard seek every tick (see
# VideoFrameReader) is what keeps the preview correctly in sync with the
# audio, but that's noticeably slower than sequential decoding for
# long-GOP-encoded footage, so a high tick rate would just fall behind
# and stutter. The audio itself plays continuously and isn't affected.
PLAYBACK_TICK_MS = 100

PROJECT_FILETYPES = [("Create Textプロジェクト", "*.json"), ("すべてのファイル", "*.*")]

INTENSITY_LABELS = {member: INTENSITY_PRESETS[member].label for member in Intensity}
LABEL_TO_INTENSITY = {label: member for member, label in INTENSITY_LABELS.items()}

MEDIA_FILETYPES = [
    ("動画・音声ファイル", "*.mp4 *.mov *.mxf *.avi *.mts *.m4v *.wav *.mp3 *.m4a *.aac *.flac"),
    ("すべてのファイル", "*.*"),
]
VIDEO_FILETYPES = [
    ("動画ファイル", "*.mp4 *.mov *.mxf *.avi *.mts *.m4v"),
    ("すべてのファイル", "*.*"),
]

MODE_AUTO = "自動文字起こし"
MODE_MANUAL = "手動（音声入力）"

PREVIEW_W, PREVIEW_H = 480, 270


def _panel(master, **kwargs):
    defaults = dict(fg_color=theme.BG_PANEL, corner_radius=14, border_width=1, border_color=theme.BORDER)
    defaults.update(kwargs)
    return ctk.CTkFrame(master, **defaults)


def _section_label(master, text):
    return ctk.CTkLabel(
        master, text=text, text_color=theme.TEXT_MUTED,
        font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12, weight="bold"),
        anchor="w",
    )


def _entry(master, **kwargs):
    defaults = dict(
        fg_color=theme.BG_FIELD, border_color=theme.BORDER, border_width=1,
        text_color=theme.TEXT, corner_radius=8,
        font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
    )
    defaults.update(kwargs)
    return ctk.CTkEntry(master, **defaults)


def _button(master, primary=True, **kwargs):
    if primary:
        defaults = dict(fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT_ON_ACCENT)
    else:
        defaults = dict(
            fg_color=theme.BG_FIELD, hover_color=theme.ACCENT_MUTED, text_color=theme.TEXT,
            border_width=1, border_color=theme.BORDER,
        )
    defaults.update(dict(corner_radius=8, font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13, weight="bold")))
    defaults.update(kwargs)
    return ctk.CTkButton(master, **defaults)


def _segmented(master, values, command=None):
    return ctk.CTkSegmentedButton(
        master, values=values, command=command,
        fg_color=theme.BG_FIELD,
        selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER,
        unselected_color=theme.BG_FIELD, unselected_hover_color=theme.ACCENT_MUTED,
        text_color=theme.TEXT, corner_radius=8,
        font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
    )


def _fmt_mmss(seconds: float) -> str:
    seconds = max(0, seconds)
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _fmt_timecode(seconds: float) -> str:
    """``MM:SS.s`` -- one decimal place, since manual segments are often
    only a couple of seconds long and whole-second display isn't precise
    enough to tell them apart.
    """

    seconds = max(0.0, seconds)
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m:02d}:{s:04.1f}"


def _parse_timecode(text: str) -> float:
    """Inverse of ``_fmt_timecode``, lenient about the input: accepts
    ``MM:SS.s``, ``SS.s``, or a bare number of seconds. Raises ``ValueError``
    on anything else.
    """

    text = text.strip()
    if ":" in text:
        minutes_str, seconds_str = text.rsplit(":", 1)
        return int(minutes_str) * 60 + float(seconds_str)
    return float(text)


class CreateTextApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("Create Text")
        self.root.geometry("900x900")
        self.root.minsize(720, 640)
        self.root.configure(fg_color=theme.BG)

        self._log_queue: "queue.Queue[tuple]" = queue.Queue()
        self._worker: threading.Thread = None
        self._temp_dir = tempfile.mkdtemp(prefix="create_text_")

        self.mode = MODE_AUTO

        # -- auto mode state --
        self.input_path = None
        self.language_label = "自動検出"
        self.model_size = transcribe_engine.DEFAULT_MODEL_SIZE
        self.segments: list[Segment] = []
        self._segment_entries: list[ctk.CTkEntry] = []

        # -- manual mode state --
        self.manual_video_path = None
        self.manual_fps = 30.0
        self.manual_duration = 0.0
        self.manual_dimensions = (1920, 1080)
        self.manual_language_label = "自動検出"
        self.manual_model_size = "small"
        self.manual_intensity_label = INTENSITY_LABELS[Intensity.STANDARD]
        self.manual_segments: list[Segment] = []
        self._manual_rows: list[dict] = []  # per-row widgets, aligned with manual_segments
        self._pending_in = None
        self._pending_out = None
        self._scrub_after_id = None
        self._preview_ctk_image = None
        self._waveform_peaks: list[float] = []
        self._mic_recorder = MicRecorder()
        self._recording_segment = None  # the Segment currently being dictated, or None
        self._wav_counter = 0

        # -- real-time preview playback state --
        self._video_reader: VideoFrameReader = None
        self._current_time = 0.0  # single source of truth for the playhead -- kept
        # in sync by scrubbing, playback, and jump-to-segment alike, so I/O and the
        # keyboard shortcuts always act on wherever the preview actually is.
        self._audio_data = None  # full decoded audio (numpy array), loaded once per video
        self._audio_samplerate = None
        self._is_playing = False
        self._playback_after_id = None
        self._playback_wall_start = None
        self._playback_video_start = None

        self._build_widgets()
        self._bind_manual_shortcuts()
        self.root.after(100, self._poll_log_queue)

    # -- top-level layout ---------------------------------------------------

    def _build_widgets(self):
        pad = {"padx": 18, "pady": 8}

        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            header, text="Create Text", text_color=theme.TEXT,
            font=ctk.CTkFont(family=theme.HEADER_FONT_FAMILY, size=28, weight="bold"),
        ).pack(anchor="w")
        self.mode_subtitle = ctk.CTkLabel(
            header, text=self.mode, text_color=theme.ACCENT,
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13, weight="bold"),
        )
        self.mode_subtitle.pack(anchor="w")

        mode_row = ctk.CTkFrame(self.root, fg_color="transparent")
        mode_row.pack(fill="x", **pad)
        self.mode_selector = _segmented(mode_row, [MODE_AUTO, MODE_MANUAL], command=self._on_mode_changed)
        self.mode_selector.set(self.mode)
        self.mode_selector.pack(fill="x")

        self.content_container = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content_container.pack(fill="both", expand=True)

        self.auto_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.manual_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self._build_auto_mode(self.auto_frame)
        self._build_manual_mode(self.manual_frame)
        self.auto_frame.pack(fill="both", expand=True)

        # -- log (shared by both modes) --
        log_panel = _panel(self.root)
        log_panel.pack(fill="x", padx=18, pady=(0, 18))
        log_inner = ctk.CTkFrame(log_panel, fg_color="transparent")
        log_inner.pack(fill="x", padx=16, pady=14)
        _section_label(log_inner, "ログ").pack(anchor="w", pady=(0, 8))
        self.log_widget = ctk.CTkTextbox(
            log_inner, fg_color=theme.BG_FIELD, text_color=theme.TEXT, corner_radius=8,
            font=ctk.CTkFont(family="Menlo", size=12), wrap="word", state="disabled", height=110,
        )
        self.log_widget.pack(fill="x")
        self.log_widget.tag_config("error", foreground=theme.ERROR)
        self.log_widget.tag_config("success", foreground=theme.SUCCESS)
        self.log_widget.tag_config("warning", foreground=theme.WARNING)

    def _on_mode_changed(self, value):
        self.mode = value
        self.mode_subtitle.configure(text=value)
        if value == MODE_AUTO:
            self.manual_frame.pack_forget()
            self.auto_frame.pack(fill="both", expand=True)
        else:
            self.auto_frame.pack_forget()
            self.manual_frame.pack(fill="both", expand=True)

    # ======================================================================
    # 自動文字起こし (auto mode)
    # ======================================================================

    def _build_auto_mode(self, parent):
        pad = {"padx": 18, "pady": 8}

        settings_panel = _panel(parent)
        settings_panel.pack(fill="x", **pad)
        inner = ctk.CTkFrame(settings_panel, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)

        file_row = ctk.CTkFrame(inner, fg_color="transparent")
        file_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(file_row, text="入力ファイル", text_color=theme.TEXT, width=90, anchor="w").pack(side="left")
        self.file_entry = _entry(file_row, state="disabled")
        self.file_entry.pack(side="left", fill="x", expand=True)
        _button(file_row, primary=False, text="参照...", width=90, command=self._browse_file).pack(
            side="left", padx=(10, 0)
        )

        _section_label(inner, "言語").pack(anchor="w", pady=(4, 4))
        self.language_selector = _segmented(
            inner, list(transcribe_engine.LANGUAGE_OPTIONS.keys()), command=self._on_language_changed
        )
        self.language_selector.set(self.language_label)
        self.language_selector.pack(fill="x", pady=(0, 8))

        _section_label(inner, "モデルサイズ（精度と速度のトレードオフ）").pack(anchor="w", pady=(0, 4))
        self.model_selector = _segmented(
            inner, transcribe_engine.MODEL_SIZES, command=self._on_model_changed
        )
        self.model_selector.set(self.model_size)
        self.model_selector.pack(fill="x")

        self.start_button = _button(
            parent, text="文字起こし開始", height=44,
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=15, weight="bold"),
            command=self._start,
        )
        self.start_button.pack(fill="x", padx=18, pady=(4, 8))

        segments_panel = _panel(parent)
        segments_panel.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        segments_inner = ctk.CTkFrame(segments_panel, fg_color="transparent")
        segments_inner.pack(fill="both", expand=True, padx=16, pady=14)
        _section_label(segments_inner, "文字起こし結果（クリックして修正できます）").pack(anchor="w", pady=(0, 8))

        self.segment_list = ctk.CTkScrollableFrame(segments_inner, fg_color=theme.BG_FIELD, corner_radius=8)
        self.segment_list.pack(fill="both", expand=True)
        self._placeholder_label = ctk.CTkLabel(
            self.segment_list, text="「文字起こし開始」を押すとここに結果が表示されます。",
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
        )
        self._placeholder_label.pack(pady=20)

        export_row = ctk.CTkFrame(parent, fg_color="transparent")
        export_row.pack(fill="x", padx=18, pady=(0, 8))
        _button(export_row, text="SRTで書き出し", command=lambda: self._export("srt")).pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        _button(export_row, primary=False, text="TXTで書き出し", command=lambda: self._export("txt")).pack(
            side="left", fill="x", expand=True, padx=6
        )
        _button(export_row, primary=False, text="VTTで書き出し", command=lambda: self._export("vtt")).pack(
            side="left", fill="x", expand=True, padx=(6, 0)
        )

    def _on_language_changed(self, value):
        self.language_label = value

    def _on_model_changed(self, value):
        self.model_size = value

    def _refresh_segment_rows(self):
        for child in self.segment_list.winfo_children():
            child.destroy()
        self._segment_entries = []

        if not self.segments:
            placeholder = ctk.CTkLabel(
                self.segment_list, text="「文字起こし開始」を押すとここに結果が表示されます。",
                text_color=theme.TEXT_MUTED, font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            )
            placeholder.pack(pady=20)
            return

        for i, seg in enumerate(self.segments):
            row = ctk.CTkFrame(self.segment_list, fg_color="transparent")
            row.pack(fill="x", pady=2, padx=2)

            timestamp = f"{_fmt_mmss(seg.start)}-{_fmt_mmss(seg.end)}"
            ctk.CTkLabel(
                row, text=timestamp, text_color=theme.TEXT_MUTED, width=110, anchor="w",
                font=ctk.CTkFont(family="Menlo", size=11),
            ).pack(side="left")

            text_entry = _entry(row)
            text_entry.insert(0, seg.text)
            text_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
            self._segment_entries.append(text_entry)

            _button(
                row, primary=False, text="✕", width=32, height=28,
                font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
                command=lambda i=i: self._delete_segment(i),
            ).pack(side="left")

    def _delete_segment(self, index: int):
        self._sync_segments_from_entries()
        preview = self.segments[index].text.strip()
        if preview:
            preview = preview if len(preview) <= 40 else preview[:39] + "…"
            message = f"このセグメントを削除しますか？\n「{preview}」"
        else:
            message = "このセグメントを削除しますか？"
        if not messagebox.askyesno("削除の確認", message):
            return
        del self.segments[index]
        self._refresh_segment_rows()

    def _sync_segments_from_entries(self):
        for seg, entry in zip(self.segments, self._segment_entries):
            seg.text = entry.get()

    def _browse_file(self):
        path = filedialog.askopenfilename(title="動画・音声ファイルを選択", filetypes=MEDIA_FILETYPES)
        if path:
            self.input_path = path
            self.file_entry.configure(state="normal")
            self.file_entry.delete(0, "end")
            self.file_entry.insert(0, path)
            self.file_entry.configure(state="disabled")

    def _export(self, fmt: str):
        self._sync_segments_from_entries()
        if not self.segments:
            messagebox.showerror("エラー", "書き出す文字起こし結果がありません。")
            return

        builders = {"srt": (build_srt, "*.srt"), "txt": (build_txt, "*.txt"), "vtt": (build_vtt, "*.vtt")}
        builder, pattern = builders[fmt]

        path = filedialog.asksaveasfilename(
            title=f"{fmt.upper()}の保存先", defaultextension=f".{fmt}",
            filetypes=[(fmt.upper(), pattern), ("すべてのファイル", "*.*")],
        )
        if not path:
            return

        with open(path, "w", encoding="utf-8") as f:
            f.write(builder(self.segments))
        self._append_log(f"{fmt.upper()}を書き出しました: {path}", tag="success")

    def _start(self):
        if self._worker is not None and self._worker.is_alive():
            return
        if not self.input_path or not os.path.isfile(self.input_path):
            messagebox.showerror("入力エラー", "動画・音声ファイルを指定してください。")
            return

        params = {
            "input_path": self.input_path,
            "language": transcribe_engine.LANGUAGE_OPTIONS[self.language_label],
            "model_size": self.model_size,
        }

        self._clear_log()
        self.start_button.configure(state="disabled")
        self._worker = threading.Thread(target=self._run_job, args=(params,), daemon=True)
        self._worker.start()

    def _run_job(self, params: dict):
        def progress_cb(message: str):
            self._log_queue.put(("log", message))

        try:
            segments = transcribe_engine.transcribe(
                params["input_path"],
                model_size=params["model_size"],
                language=params["language"],
                progress_cb=progress_cb,
            )
            self._log_queue.put(("done", segments))
        except Exception as exc:  # noqa: BLE001 -- surface any failure to the GUI
            self._log_queue.put(("error", f"{exc}\n{traceback.format_exc()}"))

    # ======================================================================
    # 手動（音声入力）(manual mode)
    # ======================================================================

    def _build_manual_mode(self, parent):
        pad = {"padx": 18, "pady": 8}

        # The preview + settings + segment list easily add up to more than
        # fits in the window at once -- wrap the whole mode in one scroll
        # area (like Auto Cut) rather than let any one section get squeezed
        # to nothing. Export buttons stay reachable by scrolling down; the
        # log panel is a sibling of this frame and always stays visible.
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        self.manual_scroll = scroll
        parent = scroll

        top_panel = _panel(parent)
        top_panel.pack(fill="x", **pad)
        top_inner = ctk.CTkFrame(top_panel, fg_color="transparent")
        top_inner.pack(fill="x", padx=16, pady=14)

        file_row = ctk.CTkFrame(top_inner, fg_color="transparent")
        file_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(file_row, text="動画ファイル", text_color=theme.TEXT, width=90, anchor="w").pack(side="left")
        self.manual_file_entry = _entry(file_row, state="disabled")
        self.manual_file_entry.pack(side="left", fill="x", expand=True)
        _button(file_row, primary=False, text="参照...", width=90, command=self._manual_browse_video).pack(
            side="left", padx=(10, 0)
        )

        project_row = ctk.CTkFrame(top_inner, fg_color="transparent")
        project_row.pack(fill="x", pady=(0, 8))
        _button(project_row, primary=False, text="プロジェクトを開く", command=self._manual_open_project).pack(
            side="left", fill="x", expand=True, padx=(0, 4)
        )
        _button(project_row, primary=False, text="プロジェクトを保存", command=self._manual_save_project).pack(
            side="left", fill="x", expand=True, padx=4
        )
        _button(project_row, primary=False, text="SRTを読み込む", command=self._manual_import_srt).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )

        settings_row = ctk.CTkFrame(top_inner, fg_color="transparent")
        settings_row.pack(fill="x")
        lang_col = ctk.CTkFrame(settings_row, fg_color="transparent")
        lang_col.pack(side="left", fill="x", expand=True, padx=(0, 8))
        _section_label(lang_col, "言語").pack(anchor="w", pady=(0, 4))
        self.manual_language_selector = _segmented(
            lang_col, list(transcribe_engine.LANGUAGE_OPTIONS.keys()), command=self._on_manual_language_changed
        )
        self.manual_language_selector.set(self.manual_language_label)
        self.manual_language_selector.pack(fill="x")

        model_col = ctk.CTkFrame(settings_row, fg_color="transparent")
        model_col.pack(side="left", fill="x", expand=True)
        _section_label(model_col, "Whisperモデル").pack(anchor="w", pady=(0, 4))
        self.manual_model_selector = _segmented(
            model_col, transcribe_engine.MODEL_SIZES, command=self._on_manual_model_changed
        )
        self.manual_model_selector.set(self.manual_model_size)
        self.manual_model_selector.pack(fill="x")

        _section_label(top_inner, "無音検出でセグメントを自動生成（既存のセグメントは置き換わります）").pack(
            anchor="w", pady=(10, 4)
        )
        auto_detect_row = ctk.CTkFrame(top_inner, fg_color="transparent")
        auto_detect_row.pack(fill="x")
        self.manual_intensity_selector = _segmented(
            auto_detect_row, [INTENSITY_LABELS[m] for m in Intensity], command=self._on_manual_intensity_changed
        )
        self.manual_intensity_selector.set(self.manual_intensity_label)
        self.manual_intensity_selector.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._auto_detect_button = _button(
            auto_detect_row, primary=False, text="セグメント自動生成", command=self._auto_detect_segments
        )
        self._auto_detect_button.pack(side="left")

        # -- preview --
        preview_panel = _panel(parent)
        preview_panel.pack(fill="x", **pad)
        preview_inner = ctk.CTkFrame(preview_panel, fg_color="transparent")
        preview_inner.pack(fill="x", padx=16, pady=14)

        self.preview_label = ctk.CTkLabel(
            preview_inner, text="動画を読み込むとここにプレビューが表示されます",
            text_color=theme.TEXT_MUTED, fg_color=theme.BG_FIELD, corner_radius=8,
            width=PREVIEW_W, height=PREVIEW_H,
        )
        self.preview_label.pack()

        self.play_button = _button(
            preview_inner, primary=False, text="▶ 再生", width=100,
            command=self._toggle_playback,
        )
        self.play_button.pack(pady=(8, 0))

        self.time_label = ctk.CTkLabel(
            preview_inner, text="00:00.0 / 00:00.0", text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(family="Menlo", size=12),
        )
        self.time_label.pack(pady=(8, 4))

        # Waveform strip, drawn once per loaded video -- helps line up
        # IN/OUT against speech/silence boundaries visually instead of only
        # by blind scrubbing or listening back afterward.
        self.waveform_canvas = tk.Canvas(preview_inner, height=50, bg=theme.BG_FIELD, highlightthickness=0)
        self.waveform_canvas.pack(fill="x", pady=(0, 4))
        self.waveform_canvas.bind("<Configure>", lambda e: self._draw_waveform())

        self.scrub_slider = ctk.CTkSlider(
            preview_inner, from_=0, to=1, number_of_steps=1000,
            fg_color=theme.BG_FIELD, progress_color=theme.ACCENT, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, command=self._on_scrub,
        )
        self.scrub_slider.set(0)
        self.scrub_slider.pack(fill="x")

        io_row = ctk.CTkFrame(preview_inner, fg_color="transparent")
        io_row.pack(fill="x", pady=(10, 0))
        self.in_label = ctk.CTkLabel(io_row, text="IN: --", text_color=theme.TEXT, width=110, anchor="w")
        self.in_label.pack(side="left")
        _button(io_row, primary=False, text="現在位置をIN", command=self._set_in).pack(side="left", padx=(0, 8))
        self.out_label = ctk.CTkLabel(io_row, text="OUT: --", text_color=theme.TEXT, width=110, anchor="w")
        self.out_label.pack(side="left")
        _button(io_row, primary=False, text="現在位置をOUT", command=self._set_out).pack(side="left", padx=(0, 8))
        _button(io_row, text="+ セグメント追加", command=self._add_manual_segment).pack(
            side="left", fill="x", expand=True
        )
        self._segment_add_button = io_row.winfo_children()[-1]

        ctk.CTkLabel(
            preview_inner,
            text="ショートカット: P=動画の再生/一時停止　I=IN設定　O=OUT設定　Enter=セグメント追加　"
                 "R=最後のセグメントを録音　Space=最後のセグメントを再生",
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(family=theme.FONT_FAMILY, size=11),
        ).pack(anchor="w", pady=(6, 0))

        # -- segment list --
        # A plain frame, not another CTkScrollableFrame -- the whole mode is
        # already wrapped in one scroll area above, and nesting scrollables
        # makes for a confusing double-scrollbar UI.
        segments_panel = _panel(parent)
        segments_panel.pack(fill="x", padx=18, pady=(0, 8))
        segments_inner = ctk.CTkFrame(segments_panel, fg_color="transparent")
        segments_inner.pack(fill="x", padx=16, pady=14)
        _section_label(segments_inner, "セグメント（IN/OUTで追加し、🎤で音声入力）").pack(anchor="w", pady=(0, 8))

        self.manual_segment_list = ctk.CTkFrame(segments_inner, fg_color=theme.BG_FIELD, corner_radius=8)
        self.manual_segment_list.pack(fill="x")
        self._manual_placeholder = ctk.CTkLabel(
            self.manual_segment_list, text="動画を読み込み、IN/OUTでセグメントを追加してください。",
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
        )
        self._manual_placeholder.pack(pady=20)

        export_row = ctk.CTkFrame(parent, fg_color="transparent")
        export_row.pack(fill="x", padx=18, pady=(0, 8))
        _button(export_row, text="SRTで書き出し", command=lambda: self._export_manual("srt")).pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        _button(
            export_row, text="XMLで書き出し（DaVinci Resolve用）", command=lambda: self._export_manual("xml")
        ).pack(side="left", fill="x", expand=True, padx=(6, 0))

    def _on_manual_language_changed(self, value):
        self.manual_language_label = value

    def _on_manual_model_changed(self, value):
        self.manual_model_size = value

    def _on_manual_intensity_changed(self, value):
        self.manual_intensity_label = value

    # -- auto-detect segments from silence -----------------------------------

    def _auto_detect_segments(self):
        if not self.manual_video_path:
            messagebox.showerror("エラー", "動画が読み込まれていません。")
            return
        if self._recording_segment is not None:
            return
        if self.manual_segments:
            if not messagebox.askyesno("確認", "既存のセグメントを無音検出の結果で置き換えますか？"):
                return

        self._auto_detect_button.configure(state="disabled")
        params = {
            "video_path": self.manual_video_path,
            "duration": self.manual_duration,
            "intensity": LABEL_TO_INTENSITY[self.manual_intensity_label].value,
        }
        threading.Thread(target=self._run_auto_detect_job, args=(params,), daemon=True).start()

    def _run_auto_detect_job(self, params: dict):
        def progress_cb(message: str):
            self._log_queue.put(("log", message))

        try:
            from silence_cut_app import cut_engine

            progress_cb("無音を検出中...")
            keep_segments = cut_engine.detect_keep_segments(
                params["video_path"], 0.0, params["duration"], params["intensity"], temp_dir=self._temp_dir,
            )
            segments = [Segment(start=start, end=end, text="") for start, end in keep_segments]
            self._log_queue.put(("auto_detect_done", segments))
        except Exception as exc:  # noqa: BLE001
            self._log_queue.put(("auto_detect_error", f"{exc}\n{traceback.format_exc()}"))

    # -- video load / preview -----------------------------------------------

    def _manual_browse_video(self):
        path = filedialog.askopenfilename(title="動画ファイルを選択", filetypes=VIDEO_FILETYPES)
        if not path:
            return

        try:
            duration = probe_duration(path)
            fps = probe_fps(path)
            dimensions = probe_dimensions(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", f"動画の読み込みに失敗しました:\n{exc}")
            return

        self.manual_video_path = path
        self.manual_duration = duration
        self.manual_fps = fps
        self.manual_dimensions = dimensions
        self.manual_segments = []
        self._pending_in = None
        self._pending_out = None
        self._update_io_labels()

        self.manual_file_entry.configure(state="normal")
        self.manual_file_entry.delete(0, "end")
        self.manual_file_entry.insert(0, path)
        self.manual_file_entry.configure(state="disabled")

        self.scrub_slider.configure(from_=0, to=max(duration, 0.1))
        self.scrub_slider.set(0)
        self._load_video_for_preview(path)
        self._update_preview_frame(0.0)
        self._refresh_manual_rows()
        self._start_waveform_job(path, duration)
        self._start_audio_load_job(path, duration)
        self._append_log(f"動画を読み込みました: {os.path.basename(path)}（{duration:.1f}秒）", tag="success")

    def _load_video_for_preview(self, path: str):
        """(Re)open the fast frame reader used for both scrubbing and
        real-time playback. Called whenever a new video becomes the loaded
        one, so an old video's reader/audio don't linger."""

        self._stop_playback()
        if self._video_reader is not None:
            self._video_reader.close()
            self._video_reader = None
        self._current_time = 0.0
        self._audio_data = None
        self._audio_samplerate = None

        try:
            self._video_reader = VideoFrameReader(path)
        except VideoFrameReaderError as exc:
            self._append_log(f"動画プレビューの初期化に失敗しました: {exc}", tag="warning")

    # -- project save/load ---------------------------------------------------

    def _manual_save_project(self):
        self._sync_manual_segments_from_entries()
        if not self.manual_video_path:
            messagebox.showerror("エラー", "動画が読み込まれていません。")
            return

        path = filedialog.asksaveasfilename(
            title="プロジェクトの保存先", defaultextension=".json", filetypes=PROJECT_FILETYPES
        )
        if not path:
            return

        save_project(
            path, self.manual_video_path, self.manual_fps, self.manual_duration,
            self.manual_dimensions, self.manual_segments,
        )
        self._append_log(f"プロジェクトを保存しました: {path}", tag="success")

    def _manual_open_project(self):
        path = filedialog.askopenfilename(title="プロジェクトを開く", filetypes=PROJECT_FILETYPES)
        if not path:
            return

        try:
            data = load_project(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", f"プロジェクトの読み込みに失敗しました:\n{exc}")
            return

        self.manual_video_path = data["video_path"]
        self.manual_fps = data["fps"]
        self.manual_duration = data["duration"]
        self.manual_dimensions = data["dimensions"]
        self.manual_segments = data["segments"]
        self._pending_in = None
        self._pending_out = None
        self._update_io_labels()

        self.manual_file_entry.configure(state="normal")
        self.manual_file_entry.delete(0, "end")
        self.manual_file_entry.insert(0, self.manual_video_path or "")
        self.manual_file_entry.configure(state="disabled")

        if self.manual_video_path and os.path.isfile(self.manual_video_path):
            self.scrub_slider.configure(from_=0, to=max(self.manual_duration, 0.1))
            self.scrub_slider.set(0)
            self._load_video_for_preview(self.manual_video_path)
            self._update_preview_frame(0.0)
            self._start_waveform_job(self.manual_video_path, self.manual_duration)
            self._start_audio_load_job(self.manual_video_path, self.manual_duration)
            self._append_log(f"プロジェクトを読み込みました: {os.path.basename(path)}", tag="success")
        else:
            self._append_log(
                f"プロジェクトを読み込みましたが、動画ファイルが見つかりません: {self.manual_video_path}\n"
                "「参照...」でファイルを選び直してください。",
                tag="warning",
            )

        self._refresh_manual_rows()

    def _manual_import_srt(self):
        path = filedialog.askopenfilename(
            title="SRTを読み込む", filetypes=[("SRTファイル", "*.srt"), ("すべてのファイル", "*.*")]
        )
        if not path:
            return

        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            segments = parse_srt(text)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", f"SRTの読み込みに失敗しました:\n{exc}")
            return

        if not segments:
            messagebox.showerror("エラー", "SRTから有効なセグメントを読み取れませんでした。")
            return

        if self.manual_segments:
            if not messagebox.askyesno("確認", "既存のセグメントをSRTの内容で置き換えますか？"):
                return

        self.manual_segments = segments
        self._pending_in = None
        self._pending_out = None
        self._update_io_labels()
        self._refresh_manual_rows()
        self._append_log(
            f"SRTを読み込みました: {os.path.basename(path)}（{len(segments)}個のセグメント）", tag="success"
        )

    # -- waveform -------------------------------------------------------------

    def _start_waveform_job(self, video_path: str, duration: float):
        self._waveform_peaks = []
        self.waveform_canvas.delete("all")
        threading.Thread(target=self._run_waveform_job, args=(video_path, duration), daemon=True).start()

    def _run_waveform_job(self, video_path: str, duration: float):
        try:
            from create_text_app.waveform import extract_waveform_peaks

            peaks = extract_waveform_peaks(video_path, duration, num_points=400, temp_dir=self._temp_dir)
            self._log_queue.put(("waveform_done", peaks))
        except Exception as exc:  # noqa: BLE001
            self._log_queue.put(("waveform_error", str(exc)))

    def _draw_waveform(self):
        canvas = self.waveform_canvas
        canvas.delete("all")
        peaks = self._waveform_peaks
        if not peaks:
            return

        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1 or height <= 1:
            return

        n = len(peaks)
        bar_width = max(width / n, 1.0)
        mid = height / 2

        for i, peak in enumerate(peaks):
            x = i * bar_width
            h = max(peak * (height / 2 - 2), 1.0)
            canvas.create_line(x, mid - h, x, mid + h, fill=theme.ACCENT, width=max(bar_width, 1.0))

    def _on_scrub(self, value):
        if self._is_playing:
            self._stop_playback()
        if self._scrub_after_id is not None:
            self.root.after_cancel(self._scrub_after_id)
        self._scrub_after_id = self.root.after(120, lambda: self._apply_scrub(float(value)))

    def _apply_scrub(self, value: float):
        self._scrub_after_id = None
        self._current_time = value
        self._update_preview_frame(value)

    def _update_preview_frame(self, time_sec: float):
        self.time_label.configure(text=f"{_fmt_timecode(time_sec)} / {_fmt_timecode(self.manual_duration)}")
        if self._video_reader is None:
            return

        try:
            img = self._video_reader.read_frame_at(time_sec)
            if img is None:
                return
            img.thumbnail((PREVIEW_W, PREVIEW_H))
            ctk_image = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._preview_ctk_image = ctk_image  # keep a reference -- CTkImage isn't retained by the widget
            self.preview_label.configure(image=ctk_image, text="")
        except Exception as exc:  # noqa: BLE001 -- preview failures shouldn't block the app
            self._append_log(f"プレビューの取得に失敗しました: {exc}", tag="warning")

    def _current_scrub_time(self) -> float:
        """The playhead's current position -- kept in sync by scrubbing,
        real-time playback, and jump-to-segment alike, so IN/OUT (mouse or
        keyboard) always act on wherever the preview actually is, playing
        or not."""

        return self._current_time

    # -- real-time playback -----------------------------------------------------

    def _start_audio_load_job(self, video_path: str, duration: float):
        threading.Thread(target=self._run_audio_load_job, args=(video_path, duration), daemon=True).start()

    def _run_audio_load_job(self, video_path: str, duration: float):
        try:
            from davinci_auto_cut.audio_extract import extract_audio_segment
            from scipy.io import wavfile

            wav_path = extract_audio_segment(video_path, 0.0, duration, sample_rate=44100, temp_dir=self._temp_dir)
            try:
                samplerate, data = wavfile.read(wav_path)
            finally:
                os.remove(wav_path)
            self._log_queue.put(("audio_load_done", (video_path, samplerate, data)))
        except Exception as exc:  # noqa: BLE001
            self._log_queue.put(("audio_load_error", str(exc)))

    def _toggle_playback(self):
        if self._is_playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        if self._video_reader is None:
            return
        if self._audio_data is None:
            self._append_log("音声を読み込み中です。少し待ってからもう一度お試しください。", tag="warning")
            return

        if self._current_time >= self.manual_duration:
            self._current_time = 0.0

        try:
            import sounddevice as sd

            start_sample = max(0, int(self._current_time * self._audio_samplerate))
            sd.play(self._audio_data[start_sample:], self._audio_samplerate)
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"音声の再生に失敗しました: {exc}", tag="warning")
            return

        self._is_playing = True
        self._playback_wall_start = time.monotonic()
        self._playback_video_start = self._current_time
        self.play_button.configure(text="⏸ 一時停止")
        self._playback_tick()

    def _stop_playback(self):
        was_playing = self._is_playing
        self._is_playing = False
        if self._playback_after_id is not None:
            self.root.after_cancel(self._playback_after_id)
            self._playback_after_id = None
        if was_playing:
            try:
                import sounddevice as sd

                sd.stop()
            except Exception:  # noqa: BLE001 -- best-effort; nothing to fall back to
                pass
        self.play_button.configure(text="▶ 再生")

    def _playback_tick(self):
        if not self._is_playing:
            return

        elapsed = time.monotonic() - self._playback_wall_start
        current = self._playback_video_start + elapsed

        if current >= self.manual_duration:
            self._current_time = self.manual_duration
            self.scrub_slider.set(self._current_time)
            self._update_preview_frame(self._current_time)
            self._stop_playback()
            return

        self._current_time = current
        self.scrub_slider.set(current)
        self._update_preview_frame(current)
        self._playback_after_id = self.root.after(PLAYBACK_TICK_MS, self._playback_tick)

    def _set_in(self):
        self._pending_in = self._current_scrub_time()
        self._update_io_labels()

    def _set_out(self):
        self._pending_out = self._current_scrub_time()
        self._update_io_labels()

    def _update_io_labels(self):
        self.in_label.configure(text=f"IN: {_fmt_timecode(self._pending_in)}" if self._pending_in is not None else "IN: --")
        self.out_label.configure(
            text=f"OUT: {_fmt_timecode(self._pending_out)}" if self._pending_out is not None else "OUT: --"
        )

    def _add_manual_segment(self):
        if self._pending_in is None or self._pending_out is None:
            messagebox.showerror("エラー", "先にIN/OUTを設定してください。")
            return
        if self._pending_out <= self._pending_in:
            messagebox.showerror("エラー", "OUTはINより後の時間にしてください。")
            return

        self.manual_segments.append(Segment(start=self._pending_in, end=self._pending_out, text=""))
        self.manual_segments.sort(key=lambda s: s.start)
        self._pending_in = None
        self._pending_out = None
        self._update_io_labels()
        self._refresh_manual_rows()

    # -- keyboard shortcuts -----------------------------------------------------

    _TEXT_INPUT_WIDGET_CLASSES = ("Entry", "TEntry", "Text")

    def _bind_manual_shortcuts(self):
        self.root.bind("<Key>", self._on_manual_key)

    def _on_manual_key(self, event):
        if self.mode != MODE_MANUAL:
            return

        # Don't hijack keystrokes while the user is typing into a field --
        # only act when focus is on something that isn't a text entry.
        focused = self.root.focus_get()
        if focused is not None and focused.winfo_class() in self._TEXT_INPUT_WIDGET_CLASSES:
            return

        key = event.keysym.lower()
        if key == "i":
            self._set_in()
        elif key == "o":
            self._set_out()
        elif key == "return":
            self._add_manual_segment()
        elif key == "r":
            if self.manual_segments:
                self._toggle_record(self.manual_segments[-1])
        elif key == "space":
            if self.manual_segments:
                self._play_segment(self.manual_segments[-1])
        elif key == "p":
            self._toggle_playback()

    # -- segment rows ---------------------------------------------------------

    def _refresh_manual_rows(self):
        for child in self.manual_segment_list.winfo_children():
            child.destroy()
        self._manual_rows = []

        if not self.manual_segments:
            placeholder = ctk.CTkLabel(
                self.manual_segment_list, text="動画を読み込み、IN/OUTでセグメントを追加してください。",
                text_color=theme.TEXT_MUTED, font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            )
            placeholder.pack(pady=20)
            return

        recording_active = self._recording_segment is not None

        for i, seg in enumerate(self.manual_segments):
            has_next = i < len(self.manual_segments) - 1
            row = ctk.CTkFrame(self.manual_segment_list, fg_color="transparent")
            row.pack(fill="x", pady=2, padx=2)

            start_entry = _entry(row, width=64, font=ctk.CTkFont(family="Menlo", size=11))
            start_entry.insert(0, _fmt_timecode(seg.start))
            start_entry.pack(side="left")

            ctk.CTkLabel(row, text="–", text_color=theme.TEXT_MUTED, width=14).pack(side="left")

            end_entry = _entry(row, width=64, font=ctk.CTkFont(family="Menlo", size=11))
            end_entry.insert(0, _fmt_timecode(seg.end))
            end_entry.pack(side="left", padx=(0, 8))

            text_entry = _entry(row)
            text_entry.insert(0, seg.text)
            text_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

            record_button = _button(
                row, primary=False, text="🎤", width=36, height=28,
                font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
                command=lambda s=seg: self._toggle_record(s),
            )
            record_button.pack(side="left", padx=(0, 4))

            play_button = _button(
                row, primary=False, text="▶", width=32, height=28,
                font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
                command=lambda s=seg: self._play_segment(s),
            )
            play_button.pack(side="left", padx=(0, 4))

            split_button = _button(
                row, primary=False, text="✂", width=32, height=28,
                font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
                command=lambda s=seg: self._split_segment(s),
            )
            split_button.pack(side="left", padx=(0, 4))

            merge_button = _button(
                row, primary=False, text="🔗", width=32, height=28,
                font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
                command=lambda s=seg: self._merge_with_next(s),
            )
            merge_button.pack(side="left", padx=(0, 4))
            if not has_next:
                merge_button.configure(state="disabled")

            delete_button = _button(
                row, primary=False, text="✕", width=32, height=28,
                font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
                command=lambda s=seg: self._delete_manual_segment(s),
            )
            delete_button.pack(side="left")

            if seg is self._recording_segment:
                record_button.configure(text="■", fg_color=theme.ERROR)
            if recording_active and seg is not self._recording_segment:
                record_button.configure(state="disabled")
                delete_button.configure(state="disabled")
                split_button.configure(state="disabled")
                merge_button.configure(state="disabled")

            self._manual_rows.append(
                {
                    "segment": seg,
                    "start_entry": start_entry,
                    "end_entry": end_entry,
                    "text_entry": text_entry,
                    "record_button": record_button,
                }
            )

        self._segment_add_button.configure(state="disabled" if recording_active else "normal")

    def _sync_manual_segments_from_entries(self):
        for row in self._manual_rows:
            seg = row["segment"]
            seg.text = row["text_entry"].get()
            try:
                seg.start = _parse_timecode(row["start_entry"].get())
                seg.end = _parse_timecode(row["end_entry"].get())
            except ValueError:
                pass  # leave the previous value -- don't blow up on a bad edit mid-typing

    def _play_segment(self, segment: Segment):
        """Jump the preview to this segment's start and play its real audio
        -- the silent scrub preview alone isn't enough to judge whether an
        IN/OUT point actually lands where the speech does.
        """

        self._stop_playback()  # don't overlap with the main preview's own playback
        self._current_time = segment.start
        self.scrub_slider.set(segment.start)
        self._update_preview_frame(segment.start)

        if not self.manual_video_path:
            return
        duration = segment.end - segment.start
        if duration <= 0:
            return

        try:
            from davinci_auto_cut.audio_extract import extract_audio_segment

            wav_path = extract_audio_segment(
                self.manual_video_path, segment.start, duration, sample_rate=44100, temp_dir=self._temp_dir,
            )
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"音声の抽出に失敗しました: {exc}", tag="warning")
            return

        try:
            audio_playback.play_wav(wav_path)
        except AudioPlaybackError as exc:
            self._append_log(str(exc), tag="warning")
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def _split_segment(self, segment: Segment):
        """Split ``segment`` in two at the current preview position -- the
        first half keeps the original text, the second half starts blank
        (there's no reliable way to guess where in the text the split
        should fall, so it's left for the user to re-dictate/re-type)."""

        if self._recording_segment is not None:
            return
        self._sync_manual_segments_from_entries()

        split_time = self._current_scrub_time()
        if not (segment.start + 0.05 < split_time < segment.end - 0.05):
            messagebox.showerror(
                "エラー",
                "分割位置がこのセグメントの範囲内にありません。\n"
                "プレビューをセグメント内の分割したい位置に移動してから分割してください。",
            )
            return

        index = next(i for i, s in enumerate(self.manual_segments) if s is segment)
        first = Segment(start=segment.start, end=split_time, text=segment.text)
        second = Segment(start=split_time, end=segment.end, text="")
        self.manual_segments[index : index + 1] = [first, second]
        self._refresh_manual_rows()
        self._append_log(
            f"セグメントを分割しました: {_fmt_timecode(first.start)}–{_fmt_timecode(first.end)} / "
            f"{_fmt_timecode(second.start)}–{_fmt_timecode(second.end)}",
            tag="success",
        )

    def _merge_with_next(self, segment: Segment):
        """Merge ``segment`` with the next one in timeline order into one,
        concatenating their text."""

        if self._recording_segment is not None:
            return
        self._sync_manual_segments_from_entries()

        index = next(i for i, s in enumerate(self.manual_segments) if s is segment)
        if index + 1 >= len(self.manual_segments):
            messagebox.showerror("エラー", "次のセグメントがないため結合できません。")
            return

        next_segment = self.manual_segments[index + 1]
        merged_text = " ".join(t for t in (segment.text.strip(), next_segment.text.strip()) if t)
        merged = Segment(start=segment.start, end=next_segment.end, text=merged_text)
        self.manual_segments[index : index + 2] = [merged]
        self._refresh_manual_rows()
        self._append_log(
            f"セグメントを結合しました: {_fmt_timecode(merged.start)}–{_fmt_timecode(merged.end)}", tag="success"
        )

    def _delete_manual_segment(self, segment: Segment):
        if self._recording_segment is not None:
            return
        self._sync_manual_segments_from_entries()

        timecode = f"{_fmt_timecode(segment.start)}–{_fmt_timecode(segment.end)}"
        preview = segment.text.strip()
        if preview:
            preview = preview if len(preview) <= 40 else preview[:39] + "…"
            message = f"このセグメントを削除しますか？\n{timecode}「{preview}」"
        else:
            message = f"このセグメントを削除しますか？\n{timecode}"
        if not messagebox.askyesno("削除の確認", message):
            return

        self.manual_segments = [s for s in self.manual_segments if s is not segment]
        self._refresh_manual_rows()

    # -- mic recording / per-segment transcription -----------------------------

    def _toggle_record(self, segment: Segment):
        if self._recording_segment is segment:
            self._stop_record_and_transcribe(segment)
        elif self._recording_segment is None:
            self._start_record(segment)
        # else: a different row is already recording -- its button is disabled, ignore.

    def _start_record(self, segment: Segment):
        self._stop_playback()  # avoid the video's own audio bleeding into the mic recording
        try:
            self._mic_recorder.start()
        except MicRecorderError as exc:
            messagebox.showerror("エラー", str(exc))
            return
        self._recording_segment = segment
        self._refresh_manual_rows()
        self._append_log(f"録音開始: {_fmt_timecode(segment.start)}–{_fmt_timecode(segment.end)}")

    def _stop_record_and_transcribe(self, segment: Segment):
        self._wav_counter += 1
        wav_path = os.path.join(self._temp_dir, f"manual_clip_{self._wav_counter}.wav")
        result_path = self._mic_recorder.stop(wav_path)
        self._recording_segment = None
        self._refresh_manual_rows()

        if not result_path:
            self._append_log("録音された音声がありませんでした。", tag="warning")
            return

        self._append_log("音声を認識中...")
        params = {
            "segment": segment,
            "wav_path": result_path,
            "model_size": self.manual_model_size,
            "language": transcribe_engine.LANGUAGE_OPTIONS[self.manual_language_label],
        }
        threading.Thread(target=self._run_manual_transcribe_job, args=(params,), daemon=True).start()

    def _run_manual_transcribe_job(self, params: dict):
        segment = params["segment"]
        wav_path = params["wav_path"]
        try:
            text = manual_transcribe.transcribe_clip(wav_path, params["model_size"], params["language"])
            self._log_queue.put(("manual_done", (segment, text)))
        except Exception as exc:  # noqa: BLE001
            self._log_queue.put(("manual_error", f"{exc}\n{traceback.format_exc()}"))
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    # -- export ---------------------------------------------------------------

    def _export_manual(self, fmt: str):
        self._sync_manual_segments_from_entries()
        if not self.manual_segments:
            messagebox.showerror("エラー", "書き出すセグメントがありません。")
            return

        if fmt == "srt":
            path = filedialog.asksaveasfilename(
                title="SRTの保存先", defaultextension=".srt",
                filetypes=[("SRT", "*.srt"), ("すべてのファイル", "*.*")],
            )
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                f.write(build_srt(self.manual_segments))
            self._append_log(f"SRTを書き出しました: {path}", tag="success")
        elif fmt == "xml":
            if not self.manual_video_path:
                messagebox.showerror("エラー", "動画が読み込まれていません。")
                return
            path = filedialog.asksaveasfilename(
                title="XMLの保存先", defaultextension=".xml",
                filetypes=[("Final Cut Pro XML", "*.xml"), ("すべてのファイル", "*.*")],
            )
            if not path:
                return
            write_marker_xml(
                path,
                sequence_name=os.path.splitext(os.path.basename(self.manual_video_path))[0],
                fps=self.manual_fps,
                video_path=self.manual_video_path,
                video_duration_sec=self.manual_duration,
                segments=self.manual_segments,
                dimensions=self.manual_dimensions,
            )
            self._append_log(f"XMLを書き出しました: {path}", tag="success")

    # ======================================================================
    # shared log/queue handling
    # ======================================================================

    def _clear_log(self):
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")

    def _append_log(self, text: str, tag: str = None):
        self.log_widget.configure(state="normal")
        if tag:
            self.log_widget.insert("end", text + "\n", tag)
        else:
            self.log_widget.insert("end", text + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                kind, payload = self._log_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "done":
                    self.segments = payload
                    self._refresh_segment_rows()
                    self._append_log(f"完了: {len(self.segments)}個のセグメントを文字起こししました。", tag="success")
                    self.start_button.configure(state="normal")
                    messagebox.showinfo("完了", "文字起こしが完了しました。")
                elif kind == "error":
                    self._append_log(f"[エラー]\n{payload}", tag="error")
                    self.start_button.configure(state="normal")
                    messagebox.showerror("エラー", "処理中にエラーが発生しました。ログを確認してください。")
                elif kind == "manual_done":
                    segment, text = payload
                    if any(s is segment for s in self.manual_segments):
                        segment.text = text
                        self._refresh_manual_rows()
                    self._append_log(f"認識結果: {text}", tag="success")
                elif kind == "manual_error":
                    self._append_log(f"[エラー]\n{payload}", tag="error")
                elif kind == "auto_detect_done":
                    self.manual_segments = payload
                    self._refresh_manual_rows()
                    self._append_log(f"完了: {len(self.manual_segments)}個のセグメントを検出しました。", tag="success")
                    self._auto_detect_button.configure(state="normal")
                elif kind == "auto_detect_error":
                    self._append_log(f"[エラー]\n{payload}", tag="error")
                    self._auto_detect_button.configure(state="normal")
                elif kind == "waveform_done":
                    self._waveform_peaks = payload
                    self._draw_waveform()
                elif kind == "waveform_error":
                    self._append_log(f"波形の生成に失敗しました: {payload}", tag="warning")
                elif kind == "audio_load_done":
                    video_path, samplerate, data = payload
                    if video_path == self.manual_video_path:  # ignore a stale job from an already-replaced video
                        self._audio_samplerate = samplerate
                        self._audio_data = data
                elif kind == "audio_load_error":
                    self._append_log(f"音声の読み込みに失敗しました: {payload}", tag="warning")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    CreateTextApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
