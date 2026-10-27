from pathlib import Path
import shutil

root = Path(__file__).resolve().parent
if not (root/'assets/library.npz').is_file():
    raise SystemExit('Missing assets/library.npz; extract the complete source package first.')
target = root/'bin/ffmpeg.exe'
if not target.is_file():
    import imageio_ffmpeg
    target.parent.mkdir(exist_ok=True)
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), target)
