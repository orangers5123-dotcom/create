"""Desktop GUI for the silence auto-cut app.

Load raw video files (or an existing FCP7 XML v5 rough sequence), or a pair
of two-camera files to sync + cut, pick a cut intensity, and write the
result back out as an FCP7 XML v5 sequence.
"""

import os
import queue
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, scrolledtext, ttk

from silence_cut_app import cut_engine
from silence_cut_app.intensity import INTENSITY_PRESETS, Intensity

VIDEO_FILETYPES = [
    ("動画ファイル", "*.mp4 *.mov *.mxf *.avi *.mts *.m4v"),
    ("すべてのファイル", "*.*"),
]
XML_FILETYPES = [("FCP7 XML", "*.xml"), ("すべてのファイル", "*.*")]


class SilenceCutApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("無音自動カット")
        self.root.geometry("720x680")
        self.root.minsize(640, 560)

        self._log_queue: "queue.Queue[tuple]" = queue.Queue()
        self._worker: threading.Thread = None

        self.mode = tk.StringVar(value="normal")  # "normal" | "twocam"
        self.input_kind = tk.StringVar(value="files")  # "files" | "xml"
        self.intensity = tk.StringVar(value=Intensity.STANDARD.value)
        self.xml_path = tk.StringVar()
        self.cam1_path = tk.StringVar()
        self.cam2_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.sequence_name = tk.StringVar(value="Silence Cut")
        self.video_files: list[str] = []

        self._build_widgets()
        self._refresh_mode_frames()
        self.root.after(100, self._poll_log_queue)

    # -- layout -----------------------------------------------------------

    def _build_widgets(self):
        pad = {"padx": 8, "pady": 6}

        mode_frame = ttk.LabelFrame(self.root, text="モード")
        mode_frame.pack(fill="x", **pad)
        ttk.Radiobutton(
            mode_frame, text="通常（動画ファイル / XML）", variable=self.mode, value="normal",
            command=self._refresh_mode_frames,
        ).pack(side="left", padx=8, pady=4)
        ttk.Radiobutton(
            mode_frame, text="2カメ同期モード", variable=self.mode, value="twocam",
            command=self._refresh_mode_frames,
        ).pack(side="left", padx=8, pady=4)

        # -- normal mode input --
        self.normal_frame = ttk.LabelFrame(self.root, text="入力（通常モード）")
        self.normal_frame.pack(fill="both", expand=True, **pad)

        kind_row = ttk.Frame(self.normal_frame)
        kind_row.pack(fill="x", padx=8, pady=4)
        ttk.Radiobutton(
            kind_row, text="動画ファイル（複数可・並び順どおりに配置）", variable=self.input_kind,
            value="files", command=self._refresh_mode_frames,
        ).pack(side="left")
        ttk.Radiobutton(
            kind_row, text="XMLファイル（単一トラックのラフタイムライン）", variable=self.input_kind,
            value="xml", command=self._refresh_mode_frames,
        ).pack(side="left", padx=(16, 0))

        self.files_frame = ttk.Frame(self.normal_frame)
        self.files_frame.pack(fill="both", expand=True, padx=8, pady=4)
        list_row = ttk.Frame(self.files_frame)
        list_row.pack(fill="both", expand=True)
        self.file_listbox = tk.Listbox(list_row, height=6, selectmode="extended")
        self.file_listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_row, orient="vertical", command=self.file_listbox.yview)
        scrollbar.pack(side="left", fill="y")
        self.file_listbox.config(yscrollcommand=scrollbar.set)

        file_btns = ttk.Frame(self.files_frame)
        file_btns.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(file_btns, text="追加...", command=self._add_files).pack(fill="x", pady=2)
        ttk.Button(file_btns, text="削除", command=self._remove_selected_files).pack(fill="x", pady=2)
        ttk.Button(file_btns, text="↑", command=lambda: self._move_file(-1)).pack(fill="x", pady=2)
        ttk.Button(file_btns, text="↓", command=lambda: self._move_file(1)).pack(fill="x", pady=2)

        self.xml_frame = ttk.Frame(self.normal_frame)
        self.xml_frame.pack(fill="x", padx=8, pady=4)
        ttk.Entry(self.xml_frame, textvariable=self.xml_path).pack(side="left", fill="x", expand=True)
        ttk.Button(self.xml_frame, text="参照...", command=self._browse_xml).pack(side="left", padx=(8, 0))

        # -- two-camera mode input --
        self.twocam_frame = ttk.LabelFrame(self.root, text="入力（2カメ同期モード）")
        self.twocam_frame.pack(fill="x", **pad)
        cam1_row = ttk.Frame(self.twocam_frame)
        cam1_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(cam1_row, text="メイン（1カメ）:", width=14).pack(side="left")
        ttk.Entry(cam1_row, textvariable=self.cam1_path).pack(side="left", fill="x", expand=True)
        ttk.Button(cam1_row, text="参照...", command=self._browse_cam1).pack(side="left", padx=(8, 0))

        cam2_row = ttk.Frame(self.twocam_frame)
        cam2_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(cam2_row, text="サブ（2カメ）:", width=14).pack(side="left")
        ttk.Entry(cam2_row, textvariable=self.cam2_path).pack(side="left", fill="x", expand=True)
        ttk.Button(cam2_row, text="参照...", command=self._browse_cam2).pack(side="left", padx=(8, 0))

        ttk.Label(
            self.twocam_frame,
            text="無音検出はメイン（1カメ）の音声を基準に行い、同じタイミングでサブ側もカットします。",
            foreground="#666",
        ).pack(anchor="w", padx=8, pady=(0, 4))

        # -- intensity --
        intensity_frame = ttk.LabelFrame(self.root, text="カット強度")
        intensity_frame.pack(fill="x", **pad)
        for member in Intensity:
            settings = INTENSITY_PRESETS[member]
            ttk.Radiobutton(
                intensity_frame, text=settings.label, variable=self.intensity, value=member.value,
            ).pack(side="left", padx=8, pady=4)

        # -- output --
        output_frame = ttk.LabelFrame(self.root, text="出力")
        output_frame.pack(fill="x", **pad)
        seq_row = ttk.Frame(output_frame)
        seq_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(seq_row, text="シーケンス名:", width=14).pack(side="left")
        ttk.Entry(seq_row, textvariable=self.sequence_name).pack(side="left", fill="x", expand=True)

        out_row = ttk.Frame(output_frame)
        out_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(out_row, text="出力XML:", width=14).pack(side="left")
        ttk.Entry(out_row, textvariable=self.output_path).pack(side="left", fill="x", expand=True)
        ttk.Button(out_row, text="参照...", command=self._browse_output).pack(side="left", padx=(8, 0))

        # -- start button --
        self.start_button = ttk.Button(self.root, text="無音カット開始", command=self._start)
        self.start_button.pack(pady=8)

        # -- log --
        log_frame = ttk.LabelFrame(self.root, text="ログ")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_widget = scrolledtext.ScrolledText(log_frame, height=10, state="disabled", wrap="word")
        self.log_widget.pack(fill="both", expand=True, padx=4, pady=4)

    def _refresh_mode_frames(self):
        if self.mode.get() == "normal":
            self.normal_frame.pack_configure()
            self.normal_frame.pack(fill="both", expand=True, padx=8, pady=6)
            self.twocam_frame.pack_forget()
        else:
            self.normal_frame.pack_forget()
            self.twocam_frame.pack(fill="x", padx=8, pady=6)

        if self.input_kind.get() == "files":
            self.files_frame.pack(fill="both", expand=True, padx=8, pady=4)
            self.xml_frame.pack_forget()
        else:
            self.files_frame.pack_forget()
            self.xml_frame.pack(fill="x", padx=8, pady=4)

    # -- file pickers -------------------------------------------------------

    def _add_files(self):
        paths = filedialog.askopenfilenames(title="動画ファイルを選択", filetypes=VIDEO_FILETYPES)
        for p in paths:
            self.video_files.append(p)
            self.file_listbox.insert("end", p)

    def _remove_selected_files(self):
        for index in reversed(self.file_listbox.curselection()):
            self.file_listbox.delete(index)
            del self.video_files[index]

    def _move_file(self, direction: int):
        selection = list(self.file_listbox.curselection())
        if len(selection) != 1:
            return
        index = selection[0]
        new_index = index + direction
        if not (0 <= new_index < len(self.video_files)):
            return
        self.video_files[index], self.video_files[new_index] = self.video_files[new_index], self.video_files[index]
        self.file_listbox.delete(0, "end")
        for p in self.video_files:
            self.file_listbox.insert("end", p)
        self.file_listbox.selection_set(new_index)

    def _browse_xml(self):
        path = filedialog.askopenfilename(title="XMLファイルを選択", filetypes=XML_FILETYPES)
        if path:
            self.xml_path.set(path)

    def _browse_cam1(self):
        path = filedialog.askopenfilename(title="メイン（1カメ）の動画を選択", filetypes=VIDEO_FILETYPES)
        if path:
            self.cam1_path.set(path)

    def _browse_cam2(self):
        path = filedialog.askopenfilename(title="サブ（2カメ）の動画を選択", filetypes=VIDEO_FILETYPES)
        if path:
            self.cam2_path.set(path)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="出力XMLの保存先", defaultextension=".xml", filetypes=XML_FILETYPES,
        )
        if path:
            self.output_path.set(path)

    # -- run ----------------------------------------------------------------

    def _validate(self):
        if self.mode.get() == "normal":
            if self.input_kind.get() == "files":
                if not self.video_files:
                    return "動画ファイルを1つ以上追加してください。"
            else:
                if not self.xml_path.get() or not os.path.isfile(self.xml_path.get()):
                    return "有効なXMLファイルを指定してください。"
        else:
            if not self.cam1_path.get() or not os.path.isfile(self.cam1_path.get()):
                return "メイン（1カメ）の動画ファイルを指定してください。"
            if not self.cam2_path.get() or not os.path.isfile(self.cam2_path.get()):
                return "サブ（2カメ）の動画ファイルを指定してください。"

        if not self.output_path.get():
            return "出力XMLの保存先を指定してください。"
        return None

    def _start(self):
        if self._worker is not None and self._worker.is_alive():
            return

        error = self._validate()
        if error:
            messagebox.showerror("入力エラー", error)
            return

        # Snapshot every Tk variable/widget value on the main thread -- Tk
        # variables and widgets must not be touched from a background
        # thread, so the worker only ever sees plain Python values.
        params = {
            "mode": self.mode.get(),
            "intensity": self.intensity.get(),
            "output_path": self.output_path.get(),
            "sequence_name": self.sequence_name.get() or "Silence Cut",
            "input_kind": self.input_kind.get(),
            "xml_path": self.xml_path.get(),
            "video_files": list(self.video_files),
            "cam1_path": self.cam1_path.get(),
            "cam2_path": self.cam2_path.get(),
        }

        self._clear_log()
        self.start_button.config(state="disabled")
        self._worker = threading.Thread(target=self._run_job, args=(params,), daemon=True)
        self._worker.start()

    def _run_job(self, params: dict):
        def progress_cb(message: str):
            self._log_queue.put(("log", message))

        try:
            if params["mode"] == "normal":
                if params["input_kind"] == "files":
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
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.config(state="disabled")

    def _append_log(self, text: str):
        self.log_widget.config(state="normal")
        self.log_widget.insert("end", text + "\n")
        self.log_widget.see("end")
        self.log_widget.config(state="disabled")

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
                        f"（{result.removed_sec:.1f}秒カット, {result.num_cuts}箇所）"
                    )
                    for warning in result.warnings:
                        self._append_log(f"[注意] {warning}")
                    self.start_button.config(state="normal")
                    messagebox.showinfo("完了", "無音カットが完了しました。")
                elif kind == "error":
                    self._append_log(f"[エラー]\n{payload}")
                    self.start_button.config(state="normal")
                    messagebox.showerror("エラー", "処理中にエラーが発生しました。ログを確認してください。")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)


def main():
    root = tk.Tk()
    SilenceCutApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
