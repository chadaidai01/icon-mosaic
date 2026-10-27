"""Resolve a public video URL to a local file; no browser credentials are read."""
from __future__ import annotations
from pathlib import Path
import os
import re
import tempfile
import threading
from urllib.parse import urlsplit
from mosaic_core import Cancelled, ffmpeg_path, probe


def normalize_video_url(text: str) -> str:
    match = re.search(r'https?://[^\s<>"\u3000]+', text.strip(), re.IGNORECASE)
    if not match:
        raise ValueError('请粘贴 http 或 https 视频链接，也可以直接粘贴包含链接的分享文字。')
    url = match.group(0).rstrip('，。；、!！?？)）]】\'')
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('视频链接格式不正确。')
    if parsed.username or parsed.password:
        raise ValueError('请使用不含用户名或密码的公开视频链接。')
    return url


def download_video_url(text, destination: Path, progress=lambda value, text: None, cancel=None):
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError('缺少链接解析组件。源码版请双击 Start.cmd 自动安装；便携版请完整解压。') from exc
    url = normalize_video_url(text)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise Cancelled()

    class Logger:
        def debug(self, message):
            pass
        def warning(self, message):
            pass
        def error(self, message):
            pass

    def on_progress(data):
        if cancel.is_set():
            raise Cancelled()
        if data.get('status') == 'downloading':
            total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            downloaded = data.get('downloaded_bytes', 0)
            fraction = min(1, downloaded/total) if total else 0
            progress(fraction*.9, f'正在下载视频 · {fraction:.0%}' if total else '正在下载视频…')
        elif data.get('status') == 'finished':
            progress(.93, '下载完成，正在整理视频文件…')

    progress(0, '正在解析视频链接…')
    with tempfile.TemporaryDirectory(prefix='_download_', dir=destination) as staging:
        staging = Path(staging)
        options = {
            'format': 'bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b',
            'outtmpl': str(staging/'%(extractor_key)s-%(id)s.%(ext)s'),
            'restrictfilenames': True,
            'noplaylist': True,
            'ignoreconfig': True,
            'merge_output_format': 'mp4',
            'ffmpeg_location': ffmpeg_path(),
            'socket_timeout': 25,
            'retries': 2,
            'fragment_retries': 2,
            'extractor_retries': 2,
            'concurrent_fragment_downloads': 3,
            'quiet': True,
            'no_warnings': True,
            'logger': Logger(),
            'progress_hooks': [on_progress],
        }
        try:
            with YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=False)
                if not info or info.get('_type') in {'playlist', 'multi_video'}:
                    raise ValueError('请使用单个视频的播放链接。')
                if cancel.is_set():
                    raise Cancelled()
                info = downloader.process_ie_result(info, download=True)
                candidates = [Path(downloader.prepare_filename(info))]
                if info.get('filepath'):
                    candidates.insert(0, Path(info['filepath']))
            if cancel.is_set():
                raise Cancelled()
            candidates += sorted((p for p in staging.iterdir() if p.suffix.lower() in {'.mp4','.mkv','.webm','.mov','.flv','.avi','.m4v'}), key=lambda p:p.stat().st_size, reverse=True)
            path = next((p for p in candidates if p.is_file()), None)
            if path is None:
                raise RuntimeError('没有找到下载完成的视频文件。')
            details = probe(path)
            target = destination/path.name
            os.replace(path, target)
            progress(1, '视频已导入，可以预览并生成图标版。')
            return dict(path=str(target), title=info.get('title') or target.stem,
                        source=url, width=details['width'], height=details['height'], duration=details['duration'])
        except Exception as exc:
            if cancel.is_set() or isinstance(exc, Cancelled):
                raise Cancelled() from exc
            detail = str(exc).replace('ERROR: ', '')
            hint = '请检查网络后稍后重试；需要登录的视频可以先自行下载，再导入本地文件。'
            raise RuntimeError('链接解析未完成：'+detail[:700]+'\n'+hint) from exc
