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
import traceback
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from davinci_auto_cut.ffprobe import probe_dimensions, probe_duration, probe_fps
from silence_cut_app import theme

from create_text_app import frame_extract, manual_transcribe, transcribe_engine
from create_text_app.fcp7_markers import write_marker_xml
from create_text_app.mic_recorder import MicRecorder, MicRecorderError
from create_text_app.subtitles import Segment, build_srt, build_txt, build_vtt

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
        self.manual_segments: list[Segment] = []
        self._manual_rows: list[dict] = []  # per-row widgets, aligned with manual_segments
        self._pending_in = None
        self._pending_out = None
        self._scrub_after_id = None
        self._preview_ctk_image = None
        self._mic_recorder = MicRecorder()
        self._recording_segment = None  # the Segment currently being dictated, or None
        self._wav_counter = 0

        self._build_widgets()
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

        self.time_label = ctk.CTkLabel(
            preview_inner, text="00:00.0 / 00:00.0", text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(family="Menlo", size=12),
        )
        self.time_label.pack(pady=(8, 4))

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
        self._update_preview_frame(0.0)
        self._refresh_manual_rows()
        self._append_log(f"動画を読み込みました: {os.path.basename(path)}（{duration:.1f}秒）", tag="success")

    def _on_scrub(self, value):
        if self._scrub_after_id is not None:
            self.root.after_cancel(self._scrub_after_id)
        self._scrub_after_id = self.root.after(120, lambda: self._apply_scrub(float(value)))

    def _apply_scrub(self, value: float):
        self._scrub_after_id = None
        self._update_preview_frame(value)

    def _update_preview_frame(self, time_sec: float):
        self.time_label.configure(text=f"{_fmt_timecode(time_sec)} / {_fmt_timecode(self.manual_duration)}")
        if not self.manual_video_path:
            return

        try:
            frame_path = os.path.join(self._temp_dir, "preview.png")
            frame_extract.extract_frame(self.manual_video_path, time_sec, out_path=frame_path)
            img = Image.open(frame_path)
            img.thumbnail((PREVIEW_W, PREVIEW_H))
            ctk_image = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._preview_ctk_image = ctk_image  # keep a reference -- CTkImage isn't retained by the widget
            self.preview_label.configure(image=ctk_image, text="")
        except Exception as exc:  # noqa: BLE001 -- preview failures shouldn't block the app
            self._append_log(f"プレビューの取得に失敗しました: {exc}", tag="warning")

    def _current_scrub_time(self) -> float:
        return float(self.scrub_slider.get())

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

        for seg in self.manual_segments:
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

            jump_button = _button(
                row, primary=False, text="▶", width=32, height=28,
                font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
                command=lambda s=seg: self._jump_to_segment(s),
            )
            jump_button.pack(side="left", padx=(0, 4))

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

    def _jump_to_segment(self, segment: Segment):
        self.scrub_slider.set(segment.start)
        self._update_preview_frame(segment.start)

    def _delete_manual_segment(self, segment: Segment):
        if self._recording_segment is not None:
            return
        self._sync_manual_segments_from_entries()
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
