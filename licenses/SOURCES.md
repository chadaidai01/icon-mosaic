# Dependency sources

The icon library is an aggregation of independently licensed artwork. Attribution and complete collection license texts are in this directory and in the raw icon library. Changes: raster normalization to 32 px; transparent artwork composited on dark/light backgrounds; optional per-cell color adjustment during video rendering.

- Dashboard Icons / Homarr Labs: https://github.com/homarr-labs/dashboard-icons/tree/83f32e08257b66fbd971ac8d7645f5b38d52e85d (Apache-2.0)
- selfh.st/icons / selfh.st: https://github.com/selfhst/icons/tree/1d65d45a42e6323b54b8096967b1ea4b65321f97 (CC-BY-4.0)
- China application and game icons: public artwork from https://app.mi.com/ and https://apps.apple.com/cn/ ; app/game names, Chinese developer/publisher evidence, image URLs and content hashes are retained in the raw library manifests. These are original copyrighted app/game marks, not covered by the open-source collection licenses above.
- Steam game icons: original artwork from Valve's public Steam CDN; read-only metadata cache https://api.steamcmd.net/ (https://github.com/steamcmd/api). AppIDs and per-image sources are retained in the raw library manifests. Copyright and trademark rights remain with their respective holders.
- Steam popularity refresh (2026-10-28): https://store.steampowered.com/charts/mostplayed and https://store.steampowered.com/charts/topselling/global ; per-game rank snapshots and artwork hashes are retained in artwork/curation.json and artwork/steam_games.json.
- FFmpeg 7.1, Gyan essentials build: https://www.gyan.dev/ffmpeg/builds/ ; source https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz ; build project https://github.com/GyanD/codexffmpeg ; unmodified binary distributed by imageio-ffmpeg 0.6.0. Full build configuration is in FFmpeg-build.txt. FFmpeg is a separate executable invoked as a subprocess, under GPLv3 or later.
- imageio-ffmpeg: https://github.com/imageio/imageio-ffmpeg ; binary distribution https://github.com/imageio/imageio-binaries
- NumPy: https://github.com/numpy/numpy
- Pillow: https://github.com/python-pillow/Pillow
- OpenCV: https://github.com/opencv/opencv
- Python: https://www.python.org/ ; https://docs.python.org/3/license.html
- PyInstaller: https://github.com/pyinstaller/pyinstaller ; GPL with bootloader distribution exception.
- yt-dlp: https://github.com/yt-dlp/yt-dlp (Unlicense for the Python package). Link importing reads public video metadata and downloads media to a local cache.
- Optional source-bootstrap Python installer: https://www.python.org/downloads/release/python-31410/ ; download URL and SHA-256 are pinned in bootstrap_config.json.

Original application code (app.py and mosaic_core.py) is provided under the MIT License. Copyright 2026. Permission is granted to use, copy, modify, merge, publish, distribute, sublicense and/or sell copies of the software, provided this notice is included. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY ARISING FROM THE SOFTWARE OR ITS USE.
