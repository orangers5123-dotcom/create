"""Desktop GUI for Create Text: local Whisper transcription with a
Vrew-style editable segment list (no video preview -- just fast subtitle
correction). Same black/purple dark theme as Auto Cut.
"""

import os
import queue
import threading
import traceback
from tkinter import filedialog, messagebox

import customtkinter as ctk

from silence_cut_app import theme

from create_text_app import transcribe_engine
from create_text_app.subtitles import Segment, build_srt, build_txt, build_vtt

MEDIA_FILETYPES = [
    ("動画・音声ファイル", "*.mp4 *.mov *.mxf *.avi *.mts *.m4v *.wav *.mp3 *.m4a *.aac *.flac"),
    ("すべてのファイル", "*.*"),
]


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


class CreateTextApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("Create Text")
        self.root.geometry("820x820")
        self.root.minsize(680, 560)
        self.root.configure(fg_color=theme.BG)

        self._log_queue: "queue.Queue[tuple]" = queue.Queue()
        self._worker: threading.Thread = None

        self.input_path = None
        self.language_label = "自動検出"
        self.model_size = transcribe_engine.DEFAULT_MODEL_SIZE

        self.segments: list[Segment] = []
        self._segment_entries: list[ctk.CTkEntry] = []

        self._build_widgets()
        self.root.after(100, self._poll_log_queue)

    # -- layout -----------------------------------------------------------

    def _build_widgets(self):
        pad = {"padx": 18, "pady": 8}

        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            header, text="Create Text", text_color=theme.TEXT,
            font=ctk.CTkFont(family=theme.HEADER_FONT_FAMILY, size=28, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text="自動文字起こし", text_color=theme.ACCENT,
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13, weight="bold"),
        ).pack(anchor="w")

        # -- settings (compact, fixed height) --
        settings_panel = _panel(self.root)
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
            self.root, text="文字起こし開始", height=44,
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=15, weight="bold"),
            command=self._start,
        )
        self.start_button.pack(fill="x", padx=18, pady=(4, 8))

        # -- segment list (the main content -- Vrew-style editable transcript) --
        segments_panel = _panel(self.root)
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

        # -- export buttons --
        export_row = ctk.CTkFrame(self.root, fg_color="transparent")
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

        # -- log --
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

    def _on_language_changed(self, value):
        self.language_label = value

    def _on_model_changed(self, value):
        self.model_size = value

    # -- segment rows -------------------------------------------------------

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
        """Pull whatever's currently in each row's entry back into
        ``self.segments`` before exporting or mutating the list.
        """

        for seg, entry in zip(self.segments, self._segment_entries):
            seg.text = entry.get()

    # -- file picker / export ------------------------------------------------

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

    # -- run ----------------------------------------------------------------

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

    # -- log/queue handling ---------------------------------------------------

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
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)


def _fmt_mmss(seconds: float) -> str:
    seconds = max(0, seconds)
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    CreateTextApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
