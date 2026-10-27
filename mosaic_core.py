"""Offline icon photomosaic video processor. Public entry points: probe, preview, convert."""
from __future__ import annotations
import dataclasses
import concurrent.futures
import json
import math
import os
import re
import unicodedata
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import cv2
import numpy as np
from PIL import Image, ImageOps

HIDE_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


class Cancelled(Exception):
    pass


@dataclasses.dataclass
class Settings:
    columns: int = 64
    height: int = 1080
    fps: float = 30.0
    tint: float = 0.55
    stable: bool = True
    domestic_share: float = 0.70
    masks: list = dataclasses.field(default_factory=list)
    start: float = 0.0
    duration: float | None = None


def ffmpeg_path() -> str:
    for p in [RESOURCE_DIR / 'bin' / 'ffmpeg.exe', RESOURCE_DIR / 'ffmpeg.exe']:
        if p.is_file():
            return str(p)
    p = shutil.which('ffmpeg')
    if p:
        return p
    try:
        import importlib
        return importlib.import_module('imageio_ffmpeg').get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError):
        pass
    raise RuntimeError('找不到 FFmpeg。请保持程序目录完整，或把 FFmpeg 加入 PATH。')


def probe(path: str | Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError('无法打开视频，请检查文件是否完整或换用 MP4 / MOV / MKV。')
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not (w > 0 and h > 0 and math.isfinite(fps) and fps > 0):
            raise ValueError('无法读取视频尺寸或帧率。')
        return dict(width=w, height=h, fps=fps, frames=int(frames), duration=frames / fps)
    finally:
        cap.release()


def dimensions(info: dict, settings: Settings) -> tuple[int, int]:
    h = settings.height or info['height']
    h = max(2, int(round(h / 2) * 2))
    w = max(2, int(round(h * info['width'] / info['height'] / 2) * 2))
    return w, h


def build_library(folder: Path, output: Path, status=lambda text: None, cancel=None) -> dict:
    """Normalize downloaded icons; exact duplicate artwork is indexed once."""
    paths = sorted(p for p in folder.rglob('*') if p.suffix.lower() in {'.png', '.webp', '.jpg', '.jpeg', '.ico', '.bmp'})
    if not paths:
        raise ValueError('此目录中没有 PNG、WebP、JPG、ICO 或 BMP 图标。')
    import hashlib
    records = {}
    for manifest in folder.rglob('manifest.json'):
        try:
            for record in json.loads(manifest.read_text(encoding='utf-8')):
                if isinstance(record, dict) and record.get('file'):
                    records[record['file']] = record
        except (ValueError, OSError, TypeError):
            pass
    curation = folder/'curation.json'
    if curation.is_file():
        for filename, patch in json.loads(curation.read_text(encoding='utf-8')).get('overrides', {}).items():
            records.setdefault(filename, {}).update(patch)
    tiles, seen, names, groups, identities, priorities = [], set(), [], [], [], []
    identity_map = {}
    group_identity_sets = {0: set(), 1: set(), 2: set()}
    group_unique = {'domestic': 0, 'steam': 0, 'general': 0}
    rejected = []
    def load(path):
        try:
            with Image.open(path) as img:
                rgba = ImageOps.contain(img.convert('RGBA'), (32, 32), Image.Resampling.LANCZOS)
                tile = Image.new('RGBA', (32, 32))
                tile.alpha_composite(rgba, ((32-rgba.width)//2, (32-rgba.height)//2))
            return path, tile, np.array(tile), None
        except Exception as e:
            return path, None, None, str(e)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)
    try:
        for i, (path, tile, pixels, error) in enumerate(pool.map(load, paths)):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if error:
                rejected.append({'file': str(path.relative_to(folder)), 'error': error})
                continue
            if pixels[:, :, 3].max() == 0:
                continue
            key = hashlib.sha256(pixels.tobytes()).digest()
            if key in seen:
                continue
            seen.add(key)
            names.append(str(path.relative_to(folder)))
            relative = path.relative_to(folder).as_posix()
            record = records.get(relative, {})
            group = 0 if relative.startswith('china_') or record.get('curated_group') == 'domestic' or record.get('category') == 'anime_game' else 1 if relative.startswith('steam_games/') else 2
            if record.get('appid'):
                identity_key = 'steam:'+str(record['appid'])
            else:
                title = record.get('identity_name', record.get('name', path.stem))
                title = re.split(r'[-—–|（(]', title, maxsplit=1)[0]
                title = unicodedata.normalize('NFKC', title).casefold()
                title = re.sub(r'(?:-dark|-light)$', '', title)
                title = re.sub(r'[^\w\u4e00-\u9fff]', '', title)
                identity_key = ('domestic:' if group == 0 else 'brand:')+title
            identity = identity_map.setdefault(identity_key, len(identity_map))
            group_identity_sets[group].add(identity)
            group_unique[['domestic', 'steam', 'general'][group]] += 1
            # Two declared compositing backgrounds improve light/dark coverage.
            for bg in (0, 250):
                base = Image.new('RGBA', (32, 32), (bg, bg, bg, 255))
                base.alpha_composite(tile)
                tiles.append(np.array(base.convert('RGB'))[:, :, ::-1].copy())
                groups.append(group)
                identities.append(identity)
                priorities.append(max(0, min(1, float(record.get('priority', 0)))))
            if i % 250 == 0:
                status(f'整理图标 {i + 1:,} / {len(paths):,}')
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    if len(tiles) < 2:
        raise ValueError('没有可用的图标图片。')
    tiles = np.asarray(tiles, np.uint8)
    status('建立颜色索引…')
    means = tiles.mean(axis=(1, 2)).astype(np.uint8)
    features = cv2.cvtColor(means.reshape(-1, 1, 3), cv2.COLOR_BGR2Lab).reshape(-1, 3).astype(np.float32)
    groups = np.asarray(groups, np.uint8)
    priorities = np.asarray(priorities, np.float32)
    identity_priorities = np.zeros(len(identity_map), np.float32)
    np.maximum.at(identity_priorities, np.asarray(identities), priorities)
    priorities = identity_priorities[np.asarray(identities)]
    group_capacities = {label: len(group_identity_sets[i]) for i, label in enumerate(['domestic', 'steam', 'general'])}
    metadata = dict(downloaded=len(paths), unique=len(names), variants=len(tiles), rejected=len(rejected), tile_size=32,
                    groups=group_unique, identities=len(identity_map), group_capacities=group_capacities, same_frame_unique=True,
                    curated_identities=int(np.count_nonzero(identity_priorities > 0)))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.npz', delete=False) as f:
        temporary = Path(f.name)
    try:
        np.savez_compressed(temporary, tiles=tiles, means=means, features=features, groups=groups,
                            identities=np.asarray(identities,np.int32), identity_labels=np.asarray(list(identity_map)),
                            priorities=priorities,
                            metadata=json.dumps(metadata), names=np.asarray(names))
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    output.with_suffix('.json').write_text(json.dumps(dict(**metadata, rejected_files=rejected), ensure_ascii=False, indent=2), encoding='utf-8')
    status(f'素材库就绪：{len(paths):,} 个文件，{len(names):,} 份不同图案')
    return metadata


class Mosaic:
    def __init__(self, library: Path):
        with np.load(library, allow_pickle=False) as data:
            self.tiles = data['tiles']
            self.means = data['means'].astype(np.float32)
            self.groups = data['groups'] if 'groups' in data else np.full(len(self.tiles), 2, np.uint8)
            self.identities = data['identities'] if 'identities' in data else np.arange(len(self.tiles),dtype=np.int32)//2
            self.priorities = data['priorities'] if 'priorities' in data else np.zeros(len(self.tiles),np.float32)
            self.features = data['features'] if 'features' in data else cv2.cvtColor(self.means.astype(np.uint8).reshape(-1,1,3),cv2.COLOR_BGR2Lab).reshape(-1,3).astype(np.float32)
            self.metadata = json.loads(str(data['metadata']))
        self._scaled = {}
        self._previous = None
        self._shape = None
        self._rank_cache = {}
        self._pools = {g: np.flatnonzero(self.groups == g) for g in [0,1]}
        self._pools[2] = np.arange(len(self.tiles))
        self._capacities = {g: len(np.unique(self.identities[ids])) for g,ids in self._pools.items()}
        self._identity_count = int(self.identities.max())+1
        self._reference_targets = None

    def reset(self):
        self._previous = None

    def _ranked(self, group, color_key):
        key = (group,int(color_key))
        if key not in self._rank_cache:
            b,g,r = color_key//256, (color_key//16)%16, color_key%16
            color = np.array([[[b*16+8,g*16+8,r*16+8]]],np.uint8)
            lab = cv2.cvtColor(color,cv2.COLOR_BGR2Lab).reshape(3).astype(np.float32)
            pool = self._pools[group]
            delta = self.features[pool]-lab
            distances = np.einsum('ij,ij->i',delta,delta) + (1-self.priorities[pool])*240
            order = pool[np.argsort(distances,kind='stable')]
            _,first = np.unique(self.identities[order],return_index=True)
            self._rank_cache[key] = order[np.sort(first)]
            if len(self._rank_cache)>8192:
                self._rank_cache.pop(next(iter(self._rank_cache)))
        return self._rank_cache[key]

    def _layout(self,w,h,columns,share):
        cell = max(6, int(round(w / max(8, min(columns, 200)))))
        cols, rows = math.ceil(w/cell),math.ceil(h/cell)
        n=rows*cols
        group = np.full(n,2,np.uint8)
        if share>=0 and (self._capacities[0] or self._capacities[1]):
            order=np.random.default_rng(20261028).permutation(n)
            group[:]=1;group[order[:round(n*max(0,min(1,share)))]]=0
        if n > self._capacities[2]:
            raise ValueError(f'当前密度需要 {n} 个不同图标，整个素材库仅有 {self._capacities[2]} 个。请降低横向图标数量，或补充素材。')
        return cell,cols,rows,group

    def render(self, frame: np.ndarray, columns: int = 64, tint: float = 0.55, stable: bool = True, domestic_share: float = .70) -> np.ndarray:
        h, w = frame.shape[:2]
        cell,cols,rows,group = self._layout(w,h,columns,domestic_share)
        if cell not in self._scaled:
            self._scaled.clear()
            self._scaled[cell] = np.stack([cv2.resize(t, (cell, cell), interpolation=cv2.INTER_AREA if cell < 32 else cv2.INTER_CUBIC) for t in self.tiles])
        padded = cv2.copyMakeBorder(frame, 0, rows*cell-h, 0, cols*cell-w, cv2.BORDER_REPLICATE)
        small = cv2.resize(padded, (cols, rows), interpolation=cv2.INTER_AREA)
        quant = small.reshape(-1, 3).astype(np.int32) >> 4
        keys = quant[:, 0]*256 + quant[:, 1]*16 + quant[:, 2]
        target = small.reshape(-1, 3).astype(np.float32)
        shape = (rows, cols, cell, domestic_share)
        n=rows*cols
        chosen=np.full(n,-1,np.int32)
        used=np.zeros(self._identity_count,bool)
        reference=target.copy()
        if stable and self._shape == shape and self._previous is not None:
            locked=np.max(np.abs(self._reference_targets-target),axis=1)<=6
            chosen[locked]=self._previous[locked]
            used[self.identities[chosen[locked]]]=True
            reference[locked]=self._reference_targets[locked]
        for pos in np.random.default_rng(747).permutation(n):
            if chosen[pos]>=0:continue
            preferred = int(group[pos])
            fallbacks = (preferred, 1-preferred, 2) if preferred in (0,1) else (2,)
            tile = None
            for candidate_group in fallbacks:
                ranking = self._ranked(candidate_group,int(keys[pos]))
                available = ~used[self.identities[ranking]]
                if available.any():
                    tile = int(ranking[int(np.argmax(available))])
                    break
            if tile is None:
                raise ValueError('整个素材库的不同图标已用完，请降低密度或补充素材。')
            chosen[pos]=tile;used[self.identities[tile]]=True
        self._previous, self._shape = chosen, shape
        self._reference_targets=reference
        unique_count=len(np.unique(self.identities[chosen]))
        if unique_count!=n:
            raise RuntimeError('同帧去重检查失败，已停止输出。')
        self.last_summary=dict(tiles=n,unique_icons=unique_count)
        patches = self._scaled[cell][chosen]
        if tint > 0:
            offset = (target-self.means[chosen]) * max(0, min(tint, 1))
            offset = np.clip(offset, -60, 60).astype(np.int16)
            patches = np.clip(patches.astype(np.int16) + offset[:, None, None, :], 0, 255).astype(np.uint8)
        return patches.reshape(rows, cols, cell, cell, 3).transpose(0, 2, 1, 3, 4).reshape(rows*cell, cols*cell, 3)[:h, :w].copy()


def remove_regions(frame: np.ndarray, regions: list) -> np.ndarray:
    if not regions:
        return frame
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for x, y, rw, rh in regions:
        left, top = max(1, int(x*w)), max(1, int(y*h))
        right, bottom = min(w-1, int((x+rw)*w)), min(h-1, int((y+rh)*h))
        if right > left and bottom > top:
            mask[top:bottom, left:right] = 255
    return cv2.inpaint(frame, mask, 3, cv2.INPAINT_TELEA)


def preview(path, engine: Mosaic, settings: Settings, second: float = 0):
    cap = cv2.VideoCapture(str(path))
    try:
        info = probe(path)
        cap.set(cv2.CAP_PROP_POS_MSEC, min(max(0, second), max(0, info['duration']-.1))*1000)
        ok, frame = cap.read()
        if not ok:
            raise ValueError('无法读取这一帧。')
        w, h = dimensions(info, settings)
        frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
        cleaned = remove_regions(frame, settings.masks)
        engine.reset()
        return frame, engine.render(cleaned, settings.columns, settings.tint, False, settings.domestic_share)
    finally:
        cap.release()


def _filters(settings, width, height, fps, source_width, source_height):
    # Set frame timing before spatial filters to preserve the final input frame.
    parts = [f'fps={fps:.8f}']
    for x, y, rw, rh in settings.masks:
        # Normalized rectangles are interpreted in the source's display coordinates.
        left, top = max(1, int(x*source_width)), max(1, int(y*source_height))
        right = min(source_width-2, int((x+rw)*source_width))
        bottom = min(source_height-2, int((y+rh)*source_height))
        if right > left and bottom > top:
            parts.append(f'delogo=x={left}:y={top}:w={right-left}:h={bottom-top}:show=0')
    parts += [f'scale={width}:{height}:flags=lanczos', 'setsar=1']
    return ','.join(parts)


def convert(input_path: Path, output_path: Path, library: Path, settings: Settings,
            progress=lambda value, text: None, cancel: threading.Event | None = None, overwrite=False):
    cancel = cancel or threading.Event()
    input_path, output_path = Path(input_path).resolve(), Path(output_path).resolve()
    if input_path == output_path:
        raise ValueError('输出不能覆盖输入视频，请选择另一个文件名。')
    if output_path.exists() and not overwrite:
        raise FileExistsError('输出文件已存在，请选择新名称。')
    info = probe(input_path)
    w, h = dimensions(info, settings)
    fps = settings.fps or min(60, info['fps'])
    if not (1 <= fps <= 120 and 16 <= settings.columns <= 200):
        raise ValueError('帧率或图标密度超出支持范围。')
    if settings.domestic_share != -1 and not 0 <= settings.domestic_share <= 1:
        raise ValueError('国内比例必须在 0 到 1 之间，或用 -1 表示自由匹配。')
    duration = max(0, info['duration']-settings.start)
    if settings.duration is not None:
        duration = min(duration, settings.duration)
    if duration <= 0:
        raise ValueError('所选时间范围中没有视频。')
    total = max(1, round(duration*fps))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    executable = ffmpeg_path()
    progress(0, '载入图标与颜色索引…')
    engine = Mosaic(library)
    procs = []
    with tempfile.TemporaryDirectory(prefix='_iconmosaic_', dir=output_path.parent) as scratch:
        scratch = Path(scratch)
        decode_log = open(scratch/'decode.log', 'wb')
        encode_log = open(scratch/'encode.log', 'wb')
        try:
            decoder = subprocess.Popen([executable, '-hide_banner', '-loglevel', 'error', '-nostdin',
                '-ss', str(settings.start), '-i', str(input_path), '-t', str(duration),
                '-vf', _filters(settings, w, h, fps, info['width'], info['height']), '-fps_mode', 'passthrough', '-an', '-f', 'rawvideo', '-pix_fmt', 'bgr24', 'pipe:1'],
                stdout=subprocess.PIPE, stderr=decode_log, creationflags=HIDE_WINDOW)
            procs.append(decoder)
            encoder = subprocess.Popen([executable, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{w}x{h}', '-r', str(fps), '-i', 'pipe:0',
                '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-maxrate', '24M', '-bufsize', '48M', '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', str(scratch/'picture.mp4')],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=encode_log, creationflags=HIDE_WINDOW)
            procs.append(encoder)
            frame_size, count, began = w*h*3, 0, time.monotonic()
            while True:
                if cancel.is_set():
                    raise Cancelled()
                raw = decoder.stdout.read(frame_size)
                if not raw:
                    break
                if len(raw) != frame_size:
                    raise RuntimeError('视频解码中断：收到不完整的画面。')
                image = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
                encoder.stdin.write(engine.render(image, settings.columns, settings.tint, settings.stable, settings.domestic_share).tobytes())
                count += 1
                if count % 5 == 0:
                    rate = count/max(.01, time.monotonic()-began)
                    eta = max(0, total-count)/max(.1, rate)
                    progress(min(.96, count/total*.96), f'{count:,} / 约 {total:,} 帧 · {rate:.1f} 帧/秒 · 约剩 {eta:.0f} 秒')
            encoder.stdin.close()
            decoder.stdout.close()
            decode_rc = decoder.wait(timeout=60)
            encode_rc = encoder.wait(timeout=120)
            if decode_rc or encode_rc or count == 0:
                decode_log.flush(); encode_log.flush()
                detail = (scratch/'decode.log').read_text(errors='replace') + (scratch/'encode.log').read_text(errors='replace')
                raise RuntimeError('视频处理失败：'+detail[-2500:])
            if cancel.is_set():
                raise Cancelled()
            progress(.97, '合并原视频声音…')
            mux_log = open(scratch/'mux.log', 'wb')
            try:
                mux = subprocess.Popen([executable, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                    '-i', str(scratch/'picture.mp4'), '-ss', str(settings.start), '-i', str(input_path),
                    '-map', '0:v:0', '-map', '1:a:0?', '-t', f'{count/fps:.8f}',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-map_metadata', '-1',
                    '-movflags', '+faststart', str(scratch/'result.mp4')],
                    stdout=subprocess.DEVNULL, stderr=mux_log, creationflags=HIDE_WINDOW)
                procs.append(mux)
                while mux.poll() is None:
                    if cancel.wait(.15):
                        raise Cancelled()
                if mux.returncode:
                    mux_log.flush()
                    raise RuntimeError('声音合并失败：'+(scratch/'mux.log').read_text(errors='replace')[-2000:])
            finally:
                if mux.poll() is None:
                    mux.terminate(); mux.wait(timeout=10)
                mux_log.close()
            os.replace(scratch/'result.mp4', output_path)
            public_settings = dataclasses.asdict(settings)
            public_settings.pop('domestic_share', None)
            result = dict(width=w, height=h, fps=fps, frames=count, duration=count/fps,
                          seconds=round(time.monotonic()-began, 2), output=str(output_path),
                          icons=engine.metadata, settings=public_settings,
                          last_frame_summary=engine.last_summary, unique_verified_frames=count)
            progress(1, f'完成 · {count/fps:.2f} 秒 · {w} × {h}')
            return result
        finally:
            for p in procs:
                if p.poll() is None:
                    p.terminate()
            for p in procs:
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait(timeout=10)
                for stream in (p.stdin, p.stdout):
                    if stream:
                        try: stream.close()
                        except (OSError, BrokenPipeError): pass
            decode_log.close(); encode_log.close()
