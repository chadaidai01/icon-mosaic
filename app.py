"""图标映像 — Windows desktop interface and command-line entry."""
from __future__ import annotations
import argparse
import dataclasses
import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
from PIL import Image, ImageTk, ImageOps
from mosaic_core import (Mosaic, Settings, Cancelled, RESOURCE_DIR,
                         build_library, convert, preview, probe)
from video_links import download_video_url

BG, PANEL, LINE = '#11151f', '#1b2130', '#303a4c'
FG, MUTED, ACCENT = '#eef2fa', '#9ba9bf', '#a5b4fc'


def app_dir():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


class App(tk.Tk):
    def __init__(self, initial=None):
        super().__init__()
        self.title('图标映像 · Icon Mosaic')
        self.geometry('1240x900')
        self.minsize(1080, 830)
        self.configure(bg=BG)
        if (RESOURCE_DIR/'assets'/'app.ico').is_file():
            self.iconbitmap(str(RESOURCE_DIR/'assets'/'app.ico'))
        self.path = None
        self.info = None
        self.library = RESOURCE_DIR/'assets'/'library.npz'
        self.engine = None
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.preview_busy = False
        self.masks = []
        self.current_original = self.current_effect = None
        self.photo = None
        self.result = None
        self.drag_start = None
        self.rect = None
        self.image_bounds = (0, 0, 1, 1)
        self.columns = tk.DoubleVar(value=64)
        self.height = tk.StringVar(value='1080p')
        self.framerate = tk.StringVar(value='跟随原片（最高 60）')
        self.tint = tk.DoubleVar(value=55)
        self.stable = tk.BooleanVar(value=True)
        self.mask_mode = tk.BooleanVar(value=False)
        self.original = tk.BooleanVar(value=False)
        self.time_value = tk.DoubleVar(value=0)
        self.url_value = tk.StringVar()
        self._configure_styles()
        self._layout()
        self.protocol('WM_DELETE_WINDOW', self.close_app)
        self.after(100, self.poll)
        self.after(200, self.load_library)
        if initial:
            self.after(400, lambda: self.load_path(initial))

    def _configure_styles(self):
        self.option_add('*Font', ('Microsoft YaHei UI', 10))
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, fieldbackground=PANEL, bordercolor=LINE)
        style.configure('TFrame', background=BG)
        style.configure('Panel.TFrame', background=PANEL)
        style.configure('TLabel', background=BG, foreground=FG)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('TButton', padding=(12, 9), background=LINE, foreground=FG, borderwidth=0)
        style.map('TButton', background=[('active', '#44506b'), ('disabled', '#222936')], foreground=[('disabled', '#637087')])
        style.configure('Accent.TButton', background=ACCENT, foreground='#101729', font=('Microsoft YaHei UI', 11, 'bold'))
        style.map('Accent.TButton', background=[('active', '#c7d2fe'), ('disabled', '#303949')])
        style.configure('TCheckbutton', background=BG, foreground=FG)
        style.map('TCheckbutton', background=[('active', BG)])
        style.configure('TCombobox', padding=6, foreground=FG, fieldbackground=PANEL, background=LINE, arrowcolor=FG)
        style.map('TCombobox', fieldbackground=[('readonly', PANEL)], foreground=[('readonly', FG)])
        style.configure('Horizontal.TProgressbar', troughcolor=PANEL, background=ACCENT, borderwidth=0)
        style.configure('Horizontal.TScale', background=BG, troughcolor=PANEL)

    def label(self, parent, text, size=10, color=FG, bold=False, **kw):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                        font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'), **kw)

    def _layout(self):
        header = tk.Frame(self, bg=BG, padx=26, pady=18)
        header.pack(fill='x')
        self.label(header, '图标映像', 24, bold=True).pack(side='left')
        self.label(header, '每一帧，都由图标组成', 11, MUTED).pack(side='left', padx=20, pady=(9, 0))
        self.label(header, '同帧去重  ·  本地处理  ·  保留原音', 10, ACCENT).pack(side='right')
        body = tk.Frame(self, bg=BG, padx=26)
        body.pack(fill='both', expand=True)
        left = tk.Frame(body, bg=BG, width=310)
        left.pack(side='left', fill='y', padx=(0, 18))
        left.pack_propagate(False)
        settings_scroll = tk.Canvas(left, bg=BG, width=290, highlightthickness=0)
        scrollbar = ttk.Scrollbar(left, orient='vertical', command=settings_scroll.yview)
        settings_scroll.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        settings_scroll.pack(side='left', fill='both', expand=True)
        side = tk.Frame(settings_scroll, bg=BG)
        settings_window = settings_scroll.create_window((0,0), window=side, anchor='nw', width=290)
        side.bind('<Configure>', lambda event: settings_scroll.configure(scrollregion=settings_scroll.bbox('all')))
        settings_scroll.bind('<Configure>', lambda event: settings_scroll.itemconfigure(settings_window, width=event.width))
        def on_wheel(event):
            widget = self.winfo_containing(event.x_root,event.y_root)
            if widget is not None and str(widget).startswith(str(left)) and not isinstance(widget,ttk.Combobox):
                settings_scroll.yview_scroll(int(-event.delta/120),'units')
        self.bind_all('<MouseWheel>', on_wheel, add='+')
        self.label(side, '01  视频与素材', 11, bold=True).pack(anchor='w', pady=(0, 10))
        self.import_button = ttk.Button(side, text='＋  导入视频', style='Accent.TButton', command=self.choose_input)
        self.import_button.pack(fill='x')
        self.label(side, '或粘贴视频链接', 9, MUTED).pack(anchor='w', pady=(10,4))
        link_row = tk.Frame(side,bg=BG)
        link_row.pack(fill='x')
        self.url_entry = ttk.Entry(link_row,textvariable=self.url_value,width=12)
        self.url_entry.pack(side='left',fill='x',expand=True,padx=(0,5))
        self.url_entry.bind('<Return>',lambda event:self.import_url())
        self.url_button = ttk.Button(link_row,text='解析导入',command=self.import_url)
        self.url_button.pack(side='right')
        self.file_label = self.label(side, '尚未选择视频', 10, MUTED, wraplength=285, justify='left')
        self.file_label.pack(anchor='w', pady=(10, 3))
        self.info_label = self.label(side, '支持 MP4 / MOV / MKV / WebM', 9, MUTED)
        self.info_label.pack(anchor='w')
        self.library_label = self.label(side, '正在载入内置素材库…', 9, ACCENT, wraplength=285, justify='left')
        self.library_label.pack(anchor='w', pady=(13, 6))
        ttk.Button(side, text='更换图标文件夹…', command=self.choose_icons).pack(fill='x')
        self.label(side, '02  拼图效果', 11, bold=True).pack(anchor='w', pady=(14, 10))
        row = tk.Frame(side, bg=BG)
        row.pack(fill='x')
        self.label(row, '横向图标数量').pack(side='left')
        self.density_label = self.label(row, '64 列', color=ACCENT)
        self.density_label.pack(side='right')
        ttk.Scale(side, from_=32, to=128, variable=self.columns, command=self.density_changed).pack(fill='x', pady=(6, 0))
        self.label(side, '少：图标更醒目     多：人物轮廓更清楚', 9, MUTED).pack(anchor='w', pady=(0, 12))
        row = tk.Frame(side, bg=BG)
        row.pack(fill='x')
        self.label(row, '输出尺寸').pack(side='left')
        ttk.Combobox(row, textvariable=self.height, values=['1080p', '720p', '原始尺寸'], state='readonly', width=12).pack(side='right')
        row = tk.Frame(side, bg=BG)
        row.pack(fill='x', pady=8)
        self.label(row, '输出帧率').pack(side='left')
        ttk.Combobox(row, textvariable=self.framerate, values=['跟随原片（最高 60）', '30 fps', '24 fps', '15 fps'], state='readonly', width=20).pack(side='right')
        self.label(side, '轮廓增强（0 = 保留图标原色）', 9, MUTED).pack(anchor='w', pady=(8, 0))
        ttk.Scale(side, from_=0, to=70, variable=self.tint).pack(fill='x', pady=(5, 4))
        ttk.Checkbutton(side, text='减少静止区域的图标闪烁', variable=self.stable).pack(anchor='w', pady=4)
        self.label(side, '03  去水印区域（可选）', 11, bold=True).pack(anchor='w', pady=(13, 8))
        ttk.Checkbutton(side, text='在原画上拖动框选区域', variable=self.mask_mode, command=self.toggle_mask).pack(anchor='w')
        row = tk.Frame(side, bg=BG)
        row.pack(fill='x', pady=7)
        ttk.Button(row, text='撤销上一个', command=self.undo_mask).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='清空全部选区', command=self.clear_masks).pack(side='left', padx=(6, 0))
        self.mask_label = self.label(side, '已选 0 个区域', 9, MUTED)
        self.mask_label.pack(anchor='w')
        self.label(side, '只处理固定位置的台标、账号和水印；框选后会自动刷新预览。', 9, MUTED, wraplength=250, justify='left').pack(anchor='w', pady=(4, 0))
        right = tk.Frame(body, bg=BG)
        right.pack(side='left', fill='both', expand=True)
        row = tk.Frame(right, bg=BG)
        row.pack(fill='x', pady=(0, 10))
        self.label(row, '效果预览', 12, bold=True).pack(side='left')
        ttk.Checkbutton(row, text='查看原画', variable=self.original, command=self.draw_preview).pack(side='right')
        self.canvas = tk.Canvas(right, bg='#080b12', highlightthickness=1, highlightbackground=LINE)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda event: self.draw_preview())
        self.canvas.bind('<ButtonPress-1>', self.begin_mask)
        self.canvas.bind('<B1-Motion>', self.drag_mask)
        self.canvas.bind('<ButtonRelease-1>', self.end_mask)
        row = tk.Frame(right, bg=BG)
        row.pack(fill='x', pady=(10, 3))
        self.time_label = self.label(row, '00:00 / 00:00', 10, MUTED)
        self.time_label.pack(side='left')
        self.preview_button = ttk.Button(row, text='刷新这一帧', command=self.request_preview)
        self.preview_button.pack(side='right')
        self.timeline = ttk.Scale(right, from_=0, to=1, variable=self.time_value, command=self.time_changed)
        self.timeline.pack(fill='x')
        self.timeline.bind('<ButtonRelease-1>', lambda event: self.request_preview())
        self.label(right, '每格都是真实图标，同帧不重复；素材不足时请降低密度或扩充素材。', 9, MUTED).pack(anchor='w', pady=(7, 14))
        footer = tk.Frame(self, bg=BG, padx=26, pady=18)
        footer.pack(fill='x')
        self.progress = ttk.Progressbar(footer, maximum=1)
        self.progress.pack(fill='x', pady=(0, 10))
        self.status_label = self.label(footer, '导入视频，选择密度，然后导出。', 10, MUTED, wraplength=580, justify='left')
        self.status_label.pack(side='left')
        self.export_button = ttk.Button(footer, text='导出 MP4', style='Accent.TButton', command=self.export)
        self.export_button.pack(side='right')
        self.cancel_button = ttk.Button(footer, text='取消', command=self.cancel.set, state='disabled')
        self.cancel_button.pack(side='right', padx=8)
        self.open_button = ttk.Button(footer, text='打开输出目录', command=self.open_output, state='disabled')
        self.open_button.pack(side='right')
        self.parameter_controls = []
        def collect(parent):
            for widget in parent.winfo_children():
                if isinstance(widget, (ttk.Button, ttk.Checkbutton, ttk.Scale, ttk.Combobox, ttk.Entry)):
                    self.parameter_controls.append(widget)
                collect(widget)
        collect(side)
        self.parameter_controls.append(self.timeline)

    def post(self, kind, value):
        self.events.put((kind, value))

    def load_library(self):
        if not self.library.is_file():
            self.library_label.configure(text='内置素材缺失，可选择本地图标文件夹。')
            return
        def job():
            try: self.post('library', (self.library, Mosaic(self.library)))
            except Exception as e: self.post('error', str(e))
        threading.Thread(target=job, daemon=True).start()

    def choose_input(self):
        if self.busy: return
        path = filedialog.askopenfilename(title='导入视频', filetypes=[('视频文件', '*.mp4 *.mov *.mkv *.webm *.avi *.m4v'), ('所有文件', '*.*')])
        if path: self.load_path(path)

    def load_path(self, path):
        try:
            info = probe(path)
        except Exception as e:
            messagebox.showerror('无法导入', str(e)); return
        self.path, self.info = Path(path), info
        self.file_label.configure(text=self.path.name, fg=FG)
        self.info_label.configure(text=f"{info['width']} × {info['height']} · {info['fps']:.2f} fps · {info['duration']:.1f} 秒")
        self.timeline.configure(to=max(.1, info['duration']-.1))
        self.time_value.set(min(8, info['duration']/3))
        self.masks.clear(); self.update_mask_label()
        self.time_changed(None)
        self.request_preview()

    def import_url(self):
        if self.busy or self.preview_busy:
            return
        value = self.url_value.get().strip()
        if not value:
            messagebox.showinfo('粘贴视频链接','请先粘贴视频链接或包含链接的分享文字。')
            return
        self.cancel.clear()
        self.set_busy(True)
        self.progress['value'] = 0
        self.status_label.configure(text='正在解析视频链接…')
        def job():
            try:
                result = download_video_url(value, app_dir()/'cache'/'videos',
                    lambda v,t:self.post('progress',(v,t)),self.cancel)
                self.post('url_ready',result)
            except Cancelled:
                self.post('cancelled',None)
            except Exception as exc:
                self.post('error',str(exc))
        threading.Thread(target=job,daemon=True).start()

    def settings(self):
        fps = 0 if self.framerate.get().startswith('跟随') else float(self.framerate.get().split()[0])
        height = {'1080p': 1080, '720p': 720, '原始尺寸': 0}[self.height.get()]
        return Settings(columns=int(round(self.columns.get())), height=height, fps=fps,
                        tint=self.tint.get()/100, stable=self.stable.get(), masks=list(self.masks))

    def density_changed(self, value):
        self.density_label.configure(text=f'{int(round(float(value)))} 列')

    def time_changed(self, _):
        sec, total = self.time_value.get(), (self.info or {}).get('duration', 0)
        self.time_label.configure(text=f'{int(sec)//60:02}:{int(sec)%60:02} / {int(total)//60:02}:{int(total)%60:02}')

    def request_preview(self):
        if not self.path or not self.engine or self.preview_busy or self.busy: return
        self.preview_busy = True
        path, engine, settings, second = self.path, self.engine, self.settings(), self.time_value.get()
        self.preview_button.configure(state='disabled')
        self.import_button.configure(state='disabled')
        self.status_label.configure(text='正在生成图标预览…')
        def job():
            try: self.post('preview', preview(path, engine, settings, second))
            except Exception as e: self.post('preview_error', str(e))
        threading.Thread(target=job, daemon=True).start()

    def draw_preview(self):
        self.canvas.delete('all')
        arr = self.current_original if self.original.get() or self.mask_mode.get() else self.current_effect
        cw, ch = max(2, self.canvas.winfo_width()), max(2, self.canvas.winfo_height())
        if arr is None:
            self.canvas.create_text(cw/2, ch/2-12, text='把视频变成动态图标拼图', fill=FG, font=('Microsoft YaHei UI', 20))
            self.canvas.create_text(cw/2, ch/2+28, text='先从左侧导入视频', fill=MUTED, font=('Microsoft YaHei UI', 11)); return
        image = Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))
        image = ImageOps.contain(image, (cw, ch), Image.Resampling.LANCZOS)
        x, y = (cw-image.width)//2, (ch-image.height)//2
        self.image_bounds = (x, y, image.width, image.height)
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.create_image(x, y, anchor='nw', image=self.photo)
        if self.original.get() or self.mask_mode.get():
            for rx, ry, rw, rh in self.masks:
                self.canvas.create_rectangle(x+rx*image.width, y+ry*image.height, x+(rx+rw)*image.width,
                                             y+(ry+rh)*image.height, outline='#fbbf24', width=2)

    def toggle_mask(self):
        if self.mask_mode.get(): self.original.set(True)
        self.draw_preview()

    def begin_mask(self, event):
        if not self.mask_mode.get() or self.current_original is None or self.busy: return
        x, y, w, h = self.image_bounds
        self.drag_start = (min(max(event.x, x+1), x+w-1), min(max(event.y, y+1), y+h-1))

    def drag_mask(self, event):
        if self.drag_start is None: return
        if self.rect: self.canvas.delete(self.rect)
        x, y, w, h = self.image_bounds
        ex, ey = min(max(event.x, x+1), x+w-1), min(max(event.y, y+1), y+h-1)
        self.rect = self.canvas.create_rectangle(*self.drag_start, ex, ey, outline='#fbbf24', width=2)

    def end_mask(self, event):
        if self.drag_start is None: return
        x, y, w, h = self.image_bounds
        ex, ey = min(max(event.x, x+1), x+w-1), min(max(event.y, y+1), y+h-1)
        sx, sy = self.drag_start
        if abs(ex-sx) > 4 and abs(ey-sy) > 4:
            self.masks.append(((min(sx, ex)-x)/w, (min(sy, ey)-y)/h, abs(ex-sx)/w, abs(ey-sy)/h))
        self.drag_start = self.rect = None
        self.update_mask_label(); self.draw_preview(); self.request_preview()

    def update_mask_label(self):
        self.mask_label.configure(text=f'已选 {len(self.masks)} 个区域 · 在拼图前处理')

    def undo_mask(self):
        if self.busy: return
        if self.masks: self.masks.pop()
        self.original.set(bool(self.masks)); self.update_mask_label(); self.draw_preview(); self.request_preview()

    def clear_masks(self):
        if self.busy: return
        self.masks.clear(); self.update_mask_label(); self.draw_preview(); self.request_preview()

    def choose_icons(self):
        if self.busy or self.preview_busy: return
        folder = filedialog.askdirectory(title='选择含有 PNG / WebP / JPG / ICO 图标的文件夹（含子目录）')
        if not folder: return
        target = app_dir()/'cache'/'custom_library.npz'
        self.set_busy(True)
        self.cancel.clear()
        def job():
            try:
                build_library(Path(folder), target, lambda text: self.post('progress', (0, text)), self.cancel)
                self.post('custom_library', (target, Mosaic(target)))
            except Cancelled: self.post('cancelled', None)
            except Exception as e: self.post('error', str(e))
        threading.Thread(target=job, daemon=True).start()

    def set_busy(self, busy):
        self.busy = busy
        for control in self.parameter_controls:
            control.configure(state='disabled' if busy else 'readonly' if isinstance(control, ttk.Combobox) else 'normal')
        for button in [self.import_button, self.export_button, self.preview_button]:
            button.configure(state='disabled' if busy else 'normal')
        self.cancel_button.configure(state='normal' if busy else 'disabled')

    def export(self):
        if not self.path or not self.engine:
            messagebox.showinfo('先导入视频', '请选择一个视频，并等待素材库载入。'); return
        if self.preview_busy: return
        directory = app_dir()/'exports'
        directory.mkdir(parents=True, exist_ok=True)
        output = filedialog.asksaveasfilename(title='保存图标视频', initialdir=str(directory),
            initialfile=self.path.stem+'_图标版.mp4', defaultextension='.mp4', filetypes=[('MP4 视频', '*.mp4')])
        if not output: return
        settings, source, library = self.settings(), self.path, self.library
        self.cancel.clear(); self.set_busy(True); self.progress['value'] = 0
        def job():
            try: self.post('complete', convert(source, Path(output), library, settings,
                lambda value, text: self.post('progress', (value, text)), self.cancel, overwrite=True))
            except Cancelled: self.post('cancelled', None)
            except Exception as e: self.post('error', str(e))
        threading.Thread(target=job, daemon=True).start()

    def open_output(self):
        if self.result: os.startfile(str(Path(self.result['output']).parent))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind in {'library', 'custom_library'}:
                    self.library, self.engine = value
                    meta = self.engine.metadata
                    description = f"本地图标库：{meta.get('identities', meta['unique']):,} 个不同图标\n自动选图 · 素材不足自动补位"
                    self.library_label.configure(text=description)
                    if kind == 'custom_library': self.set_busy(False)
                    self.request_preview()
                elif kind == 'preview':
                    self.current_original, self.current_effect = value
                    self.preview_busy = False; self.preview_button.configure(state='normal'); self.import_button.configure(state='normal')
                    self.status_label.configure(text='预览就绪 · 导出会处理整个视频并保留原音')
                    self.draw_preview()
                elif kind == 'progress':
                    self.progress['value'] = value[0]; self.status_label.configure(text=value[1])
                elif kind == 'url_ready':
                    self.set_busy(False)
                    self.progress['value'] = 1
                    self.load_path(value['path'])
                    self.file_label.configure(text=value['title'])
                elif kind == 'complete':
                    self.result = value; self.set_busy(False); self.progress['value'] = 1
                    self.open_button.configure(state='normal')
                    self.status_label.configure(text=f"导出完成 · {value['duration']:.2f} 秒 · {value['width']} × {value['height']}")
                    messagebox.showinfo('导出完成', f"已保存到：\n{value['output']}")
                elif kind == 'cancelled':
                    self.set_busy(False); self.status_label.configure(text='已取消，未保存不完整的视频。')
                elif kind in {'error', 'preview_error'}:
                    self.preview_busy = False; self.set_busy(False)
                    self.status_label.configure(text='处理未完成，请检查提示。')
                    messagebox.showerror('处理未完成', str(value))
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def close_app(self):
        if self.busy:
            self.cancel.set()
            self.status_label.configure(text='正在取消并清理临时文件…')
            self.after(150, self.wait_close)
        else: self.destroy()

    def wait_close(self):
        if self.busy: self.after(150, self.wait_close)
        else: self.destroy()


def main():
    parser = argparse.ArgumentParser(description='把视频逐帧转换为软件图标马赛克。省略 --output 时打开桌面界面。')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--url', help='解析单个公开视频链接后导入')
    parser.add_argument('--download-only', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--library', type=Path, default=RESOURCE_DIR/'assets'/'library.npz')
    parser.add_argument('--build-library', type=Path, metavar='FOLDER')
    parser.add_argument('--columns', type=int, default=64)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--fps', type=float, default=0)
    parser.add_argument('--tint', type=float, default=.55)
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--duration', type=float)
    parser.add_argument('--mask', action='append', metavar='X,Y,W,H',
                        help='水印/台标区域，归一化坐标 0-1，可重复传入多次')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    if args.url:
        if args.input:
            parser.error('--url 与 --input 请只选择一个')
        imported = download_video_url(args.url,app_dir()/'cache'/'videos',lambda v,t:print(t,flush=True))
        if args.download_only:
            print(json.dumps(imported,ensure_ascii=False,indent=2))
            return
        args.input = Path(imported['path'])
    if args.build_library:
        print(json.dumps(build_library(args.build_library, args.library, lambda text: print(text, flush=True)), ensure_ascii=False)); return
    if args.output:
        if not args.input: parser.error('--output requires --input')
        masks = []
        for item in args.mask or []:
            try:
                x, y, w, h = (float(value) for value in item.split(','))
            except ValueError:
                parser.error('--mask 需要 X,Y,W,H 四个 0-1 之间的数值，例如 --mask 0.01,0.03,0.2,0.07')
            if not all(0 <= value <= 1 for value in (x, y, w, h)) or w == 0 or h == 0:
                parser.error('--mask 的四个数值都需要在 0-1 之间，且宽高大于 0')
            masks.append((x, y, w, h))
        settings = Settings(columns=args.columns, height=args.height, fps=args.fps, tint=args.tint,
            masks=masks, start=args.start, duration=args.duration)
        result = convert(args.input, args.output, args.library, settings,
                         lambda value, text: print(f'{value:.1%} {text}', flush=True), overwrite=args.overwrite)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        App(args.input).mainloop()


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        if getattr(sys, 'frozen', False):
            (app_dir()/'error.log').write_text(str(exc), encoding='utf-8')
            if any(flag in sys.argv for flag in ('--output','--url','--download-only','--build-library')):
                raise SystemExit(1)
            messagebox.showerror('图标映像', str(exc))
        else: raise
