"""Standard-library-only diagnostics, usable before third-party packages exist."""
from __future__ import annotations
from pathlib import Path
import argparse
import importlib
import json
import platform
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
MODULES = ('numpy', 'PIL.Image', 'PIL.ImageTk', 'cv2', 'tkinter', 'yt_dlp', 'imageio_ffmpeg', 'requests', 'certifi')


def check_environment(root=ROOT):
    modules = {}
    for name in MODULES:
        try:
            importlib.import_module(name)
            modules[name] = dict(ready=True)
        except Exception as exc:
            modules[name] = dict(ready=False, detail=str(exc))
    executable = None
    candidates = [str(root/'bin'/'ffmpeg.exe'), shutil.which('ffmpeg')]
    if modules['imageio_ffmpeg']['ready']:
        from imageio_ffmpeg import get_ffmpeg_exe
        candidates.append(get_ffmpeg_exe())
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            run = subprocess.run([candidate, '-version'], capture_output=True, timeout=15,
                                 creationflags=0x08000000 if sys.platform=='win32' else 0)
            if run.returncode == 0:
                executable = candidate
                break
        except (OSError, subprocess.TimeoutExpired):
            pass
    python_ready = (3,11) <= sys.version_info < (3,15) and struct.calcsize('P') == 8
    dependencies_ready = python_ready and all(x['ready'] for x in modules.values()) and executable is not None
    library_ready = (root/'assets'/'library.npz').is_file()
    return dict(python=dict(executable=sys.executable, version=platform.python_version(), ready=python_ready),
                modules=modules, ffmpeg=dict(ready=executable is not None, executable=executable),
                library=dict(ready=library_ready), dependencies_ready=dependencies_ready,
                ready=dependencies_ready and library_ready)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    print(json.dumps(check_environment(), ensure_ascii=True, indent=None if args.json else 2))
