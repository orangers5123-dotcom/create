"""Desktop GUI for Auto Cut (silence auto-cut app): a dark, black/purple
modern theme built with customtkinter.

Load raw video files (or an existing FCP7 XML v5 rough sequence), or a pair
of two-camera files to sync + cut, pick a cut intensity, and write the
result back out as an FCP7 XML v5 sequence.
"""

import os
import queue
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox

import customtkinter as ctk

from silence_cut_app import cut_engine, theme
from silence_cut_app.intensity import INTENSITY_PRESETS, Intensity

VIDEO_FILETYPES = [
    ("動画ファイル", "*.mp4 *.mov *.mxf *.avi *.mts *.m4v"),
    ("すべてのファイル", "*.*"),
]
XML_FILETYPES = [("FCP7 XML", "*.xml"), ("すべてのファイル", "*.*")]

MODE_NORMAL = "通常（動画ファイル / XML）"
MODE_TWOCAM = "2カメ同期モード"
KIND_FILES = "動画ファイル"
KIND_XML = "XMLファイル"

INTENSITY_LABELS = {member: INTENSITY_PRESETS[member].label for member in Intensity}
LABEL_TO_INTENSITY = {label: member for member, label in INTENSITY_LABELS.items()}


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
        defaults = dict(
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT_ON_ACCENT,
        )
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


class SilenceCutApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("Auto Cut")
        self.root.geometry("760x820")
        self.root.minsize(680, 560)
        self.root.configure(fg_color=theme.BG)

        self._log_queue: "queue.Queue[tuple]" = queue.Queue()
        self._worker: threading.Thread = None

        self.mode = MODE_NORMAL
        self.input_kind = KIND_FILES
        self.intensity_label = INTENSITY_LABELS[Intensity.STANDARD]
        self.video_files: list[str] = []
        self._selected_file_row = None

        self._build_widgets()
        self._refresh_mode_frames()
        self.root.after(100, self._poll_log_queue)

    # -- layout -----------------------------------------------------------

    def _build_widgets(self):
        pad = {"padx": 18, "pady": 8}

        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            header, text="Auto Cut", text_color=theme.TEXT,
            font=ctk.CTkFont(family=theme.HEADER_FONT_FAMILY, size=28, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text="無音自動カット", text_color=theme.ACCENT,
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13, weight="bold"),
        ).pack(anchor="w")

        # -- mode -- (fixed, always visible -- never worth scrolling to reach)
        mode_panel = _panel(self.root)
        mode_panel.pack(fill="x", **pad)
        inner = ctk.CTkFrame(mode_panel, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)
        _section_label(inner, "モード").pack(anchor="w", pady=(0, 8))
        self.mode_selector = _segmented(inner, [MODE_NORMAL, MODE_TWOCAM], command=self._on_mode_changed)
        self.mode_selector.set(self.mode)
        self.mode_selector.pack(fill="x")

        # Only the file/XML/2cam input details go in a scrollable area --
        # this is the one section whose height varies a lot (a long file
        # list can get tall). Mode, intensity, and output stay fixed below
        # so they're always reachable without having to discover scrolling.
        self.input_scroll = ctk.CTkScrollableFrame(self.root, fg_color="transparent")
        self.input_scroll.pack(fill="both", expand=True, padx=0, pady=0)

        # -- normal mode input --
        self.normal_frame = _panel(self.input_scroll)
        inner = ctk.CTkFrame(self.normal_frame, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=14)
        _section_label(inner, "入力（通常モード）").pack(anchor="w", pady=(0, 8))

        self.kind_selector = _segmented(inner, [KIND_FILES, KIND_XML], command=self._on_kind_changed)
        self.kind_selector.set(self.input_kind)
        self.kind_selector.pack(fill="x", pady=(0, 10))

        self.files_frame = ctk.CTkFrame(inner, fg_color="transparent")
        self.file_list = ctk.CTkScrollableFrame(
            self.files_frame, fg_color=theme.BG_FIELD, corner_radius=8, height=140,
        )
        self.file_list.pack(side="left", fill="both", expand=True)
        file_btns = ctk.CTkFrame(self.files_frame, fg_color="transparent")
        file_btns.pack(side="left", fill="y", padx=(10, 0))
        _button(file_btns, primary=False, text="追加...", width=90, command=self._add_files).pack(pady=2)
        _button(file_btns, primary=False, text="削除", width=90, command=self._remove_selected_file).pack(pady=2)
        _button(file_btns, primary=False, text="↑", width=90, command=lambda: self._move_file(-1)).pack(pady=2)
        _button(file_btns, primary=False, text="↓", width=90, command=lambda: self._move_file(1)).pack(pady=2)

        self.xml_frame = ctk.CTkFrame(inner, fg_color="transparent")
        self.xml_entry = _entry(self.xml_frame)
        self.xml_entry.pack(side="left", fill="x", expand=True)
        _button(self.xml_frame, primary=False, text="参照...", width=90, command=self._browse_xml).pack(
            side="left", padx=(10, 0)
        )

        # -- two-camera mode input --
        self.twocam_frame = _panel(self.input_scroll)
        inner = ctk.CTkFrame(self.twocam_frame, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)
        _section_label(inner, "入力（2カメ同期モード）").pack(anchor="w", pady=(0, 8))

        cam1_row = ctk.CTkFrame(inner, fg_color="transparent")
        cam1_row.pack(fill="x", pady=4)
        ctk.CTkLabel(cam1_row, text="メイン（1カメ）", text_color=theme.TEXT, width=110, anchor="w").pack(side="left")
        self.cam1_entry = _entry(cam1_row)
        self.cam1_entry.pack(side="left", fill="x", expand=True)
        _button(cam1_row, primary=False, text="参照...", width=90, command=self._browse_cam1).pack(
            side="left", padx=(10, 0)
        )

        cam2_row = ctk.CTkFrame(inner, fg_color="transparent")
        cam2_row.pack(fill="x", pady=4)
        ctk.CTkLabel(cam2_row, text="サブ（2カメ）", text_color=theme.TEXT, width=110, anchor="w").pack(side="left")
        self.cam2_entry = _entry(cam2_row)
        self.cam2_entry.pack(side="left", fill="x", expand=True)
        _button(cam2_row, primary=False, text="参照...", width=90, command=self._browse_cam2).pack(
            side="left", padx=(10, 0)
        )

        ctk.CTkLabel(
            inner,
            text="無音検出はメイン（1カメ）の音声を基準に行い、同じタイミングでサブ側もカットします。",
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(family=theme.FONT_FAMILY, size=11),
        ).pack(anchor="w", pady=(6, 0))

        # -- intensity -- (fixed, always visible)
        self.intensity_panel = _panel(self.root)
        intensity_panel = self.intensity_panel
        intensity_panel.pack(fill="x", **pad)
        inner = ctk.CTkFrame(intensity_panel, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)
        _section_label(inner, "カット強度").pack(anchor="w", pady=(0, 8))
        self.intensity_selector = _segmented(
            inner, [INTENSITY_LABELS[m] for m in Intensity], command=self._on_intensity_changed
        )
        self.intensity_selector.set(self.intensity_label)
        self.intensity_selector.pack(fill="x")

        # -- output -- (fixed, always visible -- this is what was getting lost)
        output_panel = _panel(self.root)
        output_panel.pack(fill="x", **pad)
        inner = ctk.CTkFrame(output_panel, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)
        _section_label(inner, "出力").pack(anchor="w", pady=(0, 8))

        seq_row = ctk.CTkFrame(inner, fg_color="transparent")
        seq_row.pack(fill="x", pady=4)
        ctk.CTkLabel(seq_row, text="シーケンス名", text_color=theme.TEXT, width=110, anchor="w").pack(side="left")
        self.sequence_entry = _entry(seq_row)
        self.sequence_entry.insert(0, "Silence Cut")
        self.sequence_entry.pack(side="left", fill="x", expand=True)

        out_row = ctk.CTkFrame(inner, fg_color="transparent")
        out_row.pack(fill="x", pady=4)
        ctk.CTkLabel(out_row, text="出力XML", text_color=theme.TEXT, width=110, anchor="w").pack(side="left")
        self.output_entry = _entry(out_row)
        self.output_entry.pack(side="left", fill="x", expand=True)
        _button(out_row, primary=False, text="参照...", width=90, command=self._browse_output).pack(
            side="left", padx=(10, 0)
        )

        # -- start button --
        self.start_button = _button(
            self.root, text="無音カット開始", height=44,
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=15, weight="bold"),
            command=self._start,
        )
        self.start_button.pack(fill="x", padx=18, pady=(4, 8))

        # -- log --
        log_panel = _panel(self.root)
        log_panel.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        inner = ctk.CTkFrame(log_panel, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=14)
        _section_label(inner, "ログ").pack(anchor="w", pady=(0, 8))
        self.log_widget = ctk.CTkTextbox(
            inner, fg_color=theme.BG_FIELD, text_color=theme.TEXT, corner_radius=8,
            font=ctk.CTkFont(family="Menlo", size=12), wrap="word", state="disabled",
            height=150,
        )
        self.log_widget.pack(fill="both", expand=True)
        self.log_widget.tag_config("error", foreground=theme.ERROR)
        self.log_widget.tag_config("success", foreground=theme.SUCCESS)
        self.log_widget.tag_config("warning", foreground=theme.WARNING)
        self.log_widget.tag_config("info", foreground=theme.TEXT_MUTED)

    def _refresh_mode_frames(self):
        pad = {"padx": 18, "pady": 8}
        # normal_frame/twocam_frame are the only two children of input_scroll
        # and only one is ever shown at a time, so there's no packing order
        # to preserve here -- no `before=` needed.
        if self.mode == MODE_NORMAL:
            self.twocam_frame.pack_forget()
            self.normal_frame.pack(fill="both", expand=True, **pad)
        else:
            self.normal_frame.pack_forget()
            self.twocam_frame.pack(fill="x", **pad)

        if self.input_kind == KIND_FILES:
            self.xml_frame.pack_forget()
            self.files_frame.pack(fill="both", expand=True)
        else:
            self.files_frame.pack_forget()
            self.xml_frame.pack(fill="x")

    def _on_mode_changed(self, value):
        self.mode = value
        self._refresh_mode_frames()

    def _on_kind_changed(self, value):
        self.input_kind = value
        self._refresh_mode_frames()

    def _on_intensity_changed(self, value):
        self.intensity_label = value

    # -- file list rows -----------------------------------------------------

    def _refresh_file_rows(self):
        for child in self.file_list.winfo_children():
            child.destroy()

        if self._selected_file_row is not None and self._selected_file_row >= len(self.video_files):
            self._selected_file_row = None

        for i, path in enumerate(self.video_files):
            selected = i == self._selected_file_row
            row = ctk.CTkFrame(
                self.file_list, fg_color=theme.ACCENT_MUTED if selected else "transparent", corner_radius=6,
            )
            row.pack(fill="x", pady=1, padx=2)
            label = ctk.CTkLabel(
                row, text=os.path.basename(path), text_color=theme.TEXT, anchor="w",
                font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            )
            label.pack(side="left", fill="x", expand=True, padx=8, pady=4)
            for widget in (row, label):
                widget.bind("<Button-1>", lambda _e, i=i: self._select_file_row(i))

    def _select_file_row(self, index: int):
        self._selected_file_row = index
        self._refresh_file_rows()

    # -- file pickers -------------------------------------------------------

    def _add_files(self):
        paths = filedialog.askopenfilenames(title="動画ファイルを選択", filetypes=VIDEO_FILETYPES)
        for p in paths:
            self.video_files.append(p)
        self._refresh_file_rows()

    def _remove_selected_file(self):
        if self._selected_file_row is None:
            return
        del self.video_files[self._selected_file_row]
        self._selected_file_row = None
        self._refresh_file_rows()

    def _move_file(self, direction: int):
        index = self._selected_file_row
        if index is None:
            return
        new_index = index + direction
        if not (0 <= new_index < len(self.video_files)):
            return
        self.video_files[index], self.video_files[new_index] = self.video_files[new_index], self.video_files[index]
        self._selected_file_row = new_index
        self._refresh_file_rows()

    def _browse_xml(self):
        path = filedialog.askopenfilename(title="XMLファイルを選択", filetypes=XML_FILETYPES)
        if path:
            self.xml_entry.delete(0, "end")
            self.xml_entry.insert(0, path)

    def _browse_cam1(self):
        path = filedialog.askopenfilename(title="メイン（1カメ）の動画を選択", filetypes=VIDEO_FILETYPES)
        if path:
            self.cam1_entry.delete(0, "end")
            self.cam1_entry.insert(0, path)

    def _browse_cam2(self):
        path = filedialog.askopenfilename(title="サブ（2カメ）の動画を選択", filetypes=VIDEO_FILETYPES)
        if path:
            self.cam2_entry.delete(0, "end")
            self.cam2_entry.insert(0, path)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="出力XMLの保存先", defaultextension=".xml", filetypes=XML_FILETYPES,
        )
        if path:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, path)

    # -- run ----------------------------------------------------------------

    def _validate(self):
        if self.mode == MODE_NORMAL:
            if self.input_kind == KIND_FILES:
                if not self.video_files:
                    return "動画ファイルを1つ以上追加してください。"
            else:
                xml_path = self.xml_entry.get()
                if not xml_path or not os.path.isfile(xml_path):
                    return "有効なXMLファイルを指定してください。"
        else:
            if not self.cam1_entry.get() or not os.path.isfile(self.cam1_entry.get()):
                return "メイン（1カメ）の動画ファイルを指定してください。"
            if not self.cam2_entry.get() or not os.path.isfile(self.cam2_entry.get()):
                return "サブ（2カメ）の動画ファイルを指定してください。"

        if not self.output_entry.get():
            return "出力XMLの保存先を指定してください。"
        return None

    def _start(self):
        if self._worker is not None and self._worker.is_alive():
            return

        error = self._validate()
        if error:
            messagebox.showerror("入力エラー", error)
            return

        # Snapshot every widget value on the main thread -- Tk widgets must
        # not be touched from a background thread, so the worker only ever
        # sees plain Python values.
        params = {
            "mode": self.mode,
            "intensity": LABEL_TO_INTENSITY[self.intensity_label].value,
            "output_path": self.output_entry.get(),
            "sequence_name": self.sequence_entry.get() or "Silence Cut",
            "input_kind": self.input_kind,
            "xml_path": self.xml_entry.get(),
            "video_files": list(self.video_files),
            "cam1_path": self.cam1_entry.get(),
            "cam2_path": self.cam2_entry.get(),
        }

        self._clear_log()
        self.start_button.configure(state="disabled")
        self._worker = threading.Thread(target=self._run_job, args=(params,), daemon=True)
        self._worker.start()

    def _run_job(self, params: dict):
        def progress_cb(message: str):
            self._log_queue.put(("log", message))

        try:
            if params["mode"] == MODE_NORMAL:
                if params["input_kind"] == KIND_FILES:
                    result = cut_engine.run_single_track(
                        intensity=params["intensity"],
                        output_xml_path=params["output_path"],
                        source_files=params["video_files"],
                        sequence_name=params["sequence_name"],
                        progress_cb=progress_cb,
                    )
                else:
                    result = cut_engine.run_single_track(
                        intensity=params["intensity"],
                        output_xml_path=params["output_path"],
                        xml_path=params["xml_path"],
                        sequence_name=params["sequence_name"],
                        progress_cb=progress_cb,
                    )
            else:
                result = cut_engine.run_two_camera(
                    cam1_path=params["cam1_path"],
                    cam2_path=params["cam2_path"],
                    intensity=params["intensity"],
                    output_xml_path=params["output_path"],
                    sequence_name=params["sequence_name"],
                    progress_cb=progress_cb,
                )

            self._log_queue.put(("done", result))
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
                    result: cut_engine.CutResult = payload
                    self._append_log(
                        f"完了: 入力 {result.total_input_sec:.1f}秒 → 出力 {result.total_output_sec:.1f}秒 "
                        f"（{result.removed_sec:.1f}秒カット, {result.num_cuts}箇所）",
                        tag="success",
                    )
                    for warning in result.warnings:
                        self._append_log(f"[注意] {warning}", tag="warning")
                    self.start_button.configure(state="normal")
                    messagebox.showinfo("完了", "無音カットが完了しました。")
                elif kind == "error":
                    self._append_log(f"[エラー]\n{payload}", tag="error")
                    self.start_button.configure(state="normal")
                    messagebox.showerror("エラー", "処理中にエラーが発生しました。ログを確認してください。")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    SilenceCutApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
