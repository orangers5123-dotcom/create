"""py2app build script for Auto Cut (the silence_cut_app desktop GUI).

Run on a Mac (py2app itself only works on macOS):

    pip install -r requirements.txt py2app
    python3 setup_mac_app.py py2app

The bundled .app will be under dist/Auto Cut.app. It still shells out to the
system `ffmpeg`/`ffprobe` binaries at runtime -- they are not bundled in, so
they must be installed separately (e.g. `brew install ffmpeg`) on any
machine that runs the app.
"""

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

setup(
    app=APP,
    name="Auto Cut",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
