"""py2app build script for Auto Cut (the silence_cut_app desktop GUI).

Run on a Mac (py2app itself only works on macOS):

    pip install -r requirements.txt py2app
    python3 setup_mac_app.py py2app

The bundled .app will be under dist/Auto Cut.app. It still shells out to the
system `ffmpeg`/`ffprobe` binaries at runtime -- they are not bundled in, so
they must be installed separately (e.g. `brew install ffmpeg`) on any
machine that runs the app.
"""

import sys
import threading

from setuptools import setup

APP = ["silence_cut_app/__main__.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "packages": ["numpy", "scipy", "customtkinter", "davinci_auto_cut", "silence_cut_app"],
    "plist": {
        "CFBundleName": "Auto Cut",
        "CFBundleDisplayName": "Auto Cut",
        "CFBundleIdentifier": "com.example.autocut",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
    },
}


def _run_setup():
    setup(
        app=APP,
        name="Auto Cut",
        data_files=DATA_FILES,
        options={"py2app": OPTIONS},
        setup_requires=["py2app"],
    )


if __name__ == "__main__":
    # py2app's dependency scanner (modulegraph) walks each module's AST with
    # a plain recursive visitor. numpy/scipy's import graphs are deep enough
    # that this can exceed not just Python's recursion counter but the
    # underlying C thread stack -- raising sys.setrecursionlimit() alone
    # still segfaults/RecursionErrors partway through, because the main
    # thread's stack size is fixed at process start on macOS. Running the
    # scan in a fresh thread with a much larger requested stack size (and a
    # much higher recursion limit) is the standard workaround for this exact
    # py2app + numpy/scipy combination. Build-time only; doesn't affect the
    # app's own runtime behavior.
    sys.setrecursionlimit(100000)
    threading.stack_size(256 * 1024 * 1024)  # 256MB, vs. the ~8MB default

    result = {}

    def _target():
        try:
            _run_setup()
        except BaseException as exc:  # noqa: BLE001 -- re-raise on the main thread
            result["error"] = exc

    build_thread = threading.Thread(target=_target)
    build_thread.start()
    build_thread.join()

    if "error" in result:
        raise result["error"]
