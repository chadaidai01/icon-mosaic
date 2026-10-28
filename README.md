# 图标映像 · Icon Mosaic

把一段视频逐帧重绘成**软件图标马赛克**：每一格都是一枚真实的 App / 游戏图标，图标按原画面的颜色和明暗挑选，远看是画面，近看是图标墙。全程本地处理，视频不上传；导出保留原声。

- 每帧所有格子使用**不同**图标，同一帧不会出现重复图标
- 支持本地文件导入与**公开视频链接**解析
- 可框选**任意**固定位置的水印 / 台标，在拼图前处理
- 内置 18,630 个图标文件（10,068 个不同图标身份），国内素材优先
- Windows 一键环境检查与安装，小白双击即可跑起来

## 目录

- [快速开始](#快速开始)
- [使用](#使用)
- [命令行](#命令行)
- [去水印](#去水印)
- [图标素材库](#图标素材库)
- [项目结构](#项目结构)
- [从源码构建](#从源码构建)
- [常见问题](#常见问题)
- [许可](#许可)

## 快速开始

### 方式一：便携版（推荐）

1. 从 [Release](https://github.com/chadaidai01/icon-mosaic/releases/latest) 下载 `IconMosaic-windows-x64.zip`
2. 完整解压（保留旁边的 `_internal` 文件夹）
3. 双击 `图标映像.exe`

便携版已经把 Python 运行时、NumPy / OpenCV、yt-dlp、FFmpeg 和 VC 运行库全部打包进去，**不需要装 Python**。本地视频处理无需联网，解析视频链接时需要联网。

| 文件 | 作用 |
| --- | --- |
| `图标映像.exe` | 主程序，双击打开 |
| `_internal\` | 运行时与图标索引，必须和 exe 放在同一目录 |
| `使用说明.md` | 本说明 |



其他下载：`IconMosaic-source.zip` 是附带一键启动脚本和预处理索引的源码包；`IconMosaic-icons-18630.zip` 是完整原始素材与来源清单；`SHA256SUMS.txt` 用于校验附件。

### 方式二：源码一键运行

1. 下载源码包或 `git clone`
2. 双击 **`Start.cmd`**

首次运行会检查环境：缺少 Python 时自动下载官方安装器（带 SHA-256 校验）装到项目内 `.runtime`，随后建立独立虚拟环境并安装 NumPy、Pillow、OpenCV、yt-dlp、FFmpeg 组件。依赖只装在项目目录，不污染系统 Python。

其他脚本：

| 脚本 | 作用 |
| --- | --- |
| `Start.cmd` | 检查环境 → 缺什么装什么 → 启动程序 |
| `Check.cmd` | 只做检查，输出 JSON 报告，不改动任何文件 |
| `Repair.cmd` | 修复或更新依赖后启动 |
| `Build.cmd` | 打包 Windows 便携版到 `dist\` |

也可以手动安装：

```powershell
python -m pip install -r requirements.txt
python app.py
```

## 使用

1. 点击「导入视频」选择本地文件；或把视频链接粘进输入框，点「解析导入」（支持整段分享文字）
2. 拖动「密度」滑块：列数少 → 单个图标更醒目；列数多 → 人物轮廓更清楚（1080p 默认 64 列）
3. 拖动时间轴，点「刷新这一帧」预览效果；勾选「查看原画」可对照原片
4. 需要遮水印就按下一节框选
5. 点「导出 MP4」，默认存到程序目录 `exports\`，也可另存

「轮廓增强」只微调图标亮度与色偏，设为 0 则完全保留图标原色。画面完全由图标构成，不叠加原视频像素。

## 命令行

```powershell
# 整片转换
python app.py --input 原片.mp4 --output 输出.mp4 --columns 64 --height 1080 --fps 30

# 带两个水印区域（归一化坐标，可重复传 --mask）
python app.py --input 原片.mp4 --output 输出.mp4 --mask 0.02,0.03,0.18,0.06 --mask 0.75,0.88,0.20,0.08

# 只解析下载公开视频链接
python app.py --url "https://b23.tv/xxxxxx" --download-only

# 用自定义图标目录重建索引
python app.py --build-library "D:\我的图标" --library assets\library.npz
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--input` | — | 输入视频 |
| `--output` | — | 输出 MP4；不填则打开图形界面 |
| `--columns` | 64 | 横向图标数量（16–200） |
| `--height` | 1080 | 输出高度，宽度按原比例 |
| `--fps` | 0 | 0 = 跟随原片，最高 60 |
| `--tint` | 0.55 | 轮廓增强，0–1 |
| `--start` / `--duration` | 0 / 全片 | 截取区间（秒） |
| `--mask` | 空 | 水印区域 `X,Y,W,H`（0–1），可重复 |
| `--library` | `assets/library.npz` | 图标索引 |
| `--overwrite` | 关 | 覆盖已存在的输出文件 |

## 去水印

去水印是通用功能，与具体视频无关：

1. 勾选「在原画上拖动框选区域」
2. 在预览里按住左键拖出矩形，可框选多个区域；「撤销上一个」/「清空全部选区」可回退
3. 松手后自动刷新预览，区域会在生成图标拼图之前处理

坐标以画面宽高归一化保存，所以同一组选区可以复用到同机位、同分辨率的其他片段；也支持用 `--mask` 直接传给命令行。

预览使用局部图像修补，导出使用 FFmpeg `delogo` 插值，两者边缘可能略有差异。该功能用于遮去固定位置的台标、账号、贴片水印，不追求还原被遮挡的原始细节；移动水印需要分别覆盖其活动范围。

## 图标素材库

当前索引：**18,630 个图标文件 / 18,383 张不同图案 / 10,068 个图标身份**。

本次按 Steam [热玩榜](https://store.steampowered.com/charts/mostplayed)与[热销榜](https://store.steampowered.com/charts/topselling/global)新增 337 个此前未收录的游戏图标，包括 Deadlock、Geometry Dash、The Binding of Isaac: Rebirth、Rocket League、R.E.P.O. 等。已保留上一版本的国内 App、游戏和二游素材，并更新热门选图优先级。

选图规则：先按格子颜色在素材里找最接近的图标；国内素材优先参与，某一类不够时自动用其他素材补位，不会因为某类用完而中断。同一帧内图标身份不重复；整库都不够时提示降低密度或补充素材，不会用重复图标凑数。

素材来源与许可见 [`licenses/`](licenses/)，逐文件记录来源 URL、SHA-256 与分类依据：

- [Dashboard Icons](https://github.com/homarr-labs/dashboard-icons) — Apache-2.0
- [selfh.st/icons](https://github.com/selfhst/icons) — CC-BY-4.0
- 中国应用 / 游戏 / 二游图标与 Steam 图标 — 来自各商店与官方 CDN 的公开图标，版权及商标归原权利人

也可以点「更换图标文件夹」用自己的 PNG / WebP / JPG / ICO / BMP 目录，程序会递归扫描并建立本地索引。

## 项目结构

```text
app.py               图形界面 + 命令行入口
mosaic_core.py       图标索引、选图、拼图、FFmpeg 管线
video_links.py       视频链接解析与下载
environment_check.py 环境与依赖自检（仅标准库）
bootstrap.ps1        一键检查 / 安装 / 修复环境
bootstrap_config.json Python 安装源与校验值
Start.cmd / Check.cmd / Repair.cmd / Build.cmd
build_windows.ps1    PyInstaller 打包脚本
prepare_build.py     打包前准备资源
assets/              app.ico、library.npz 图标索引
licenses/            第三方许可与素材来源清单
bin/ffmpeg.exe       可选，缺失时用 imageio-ffmpeg 提供的二进制
```

## 从源码构建

```powershell
# 需要 Python 3.11+ x64
python -m pip install -r requirements-build.txt
python prepare_build.py
powershell -ExecutionPolicy Bypass -File build_windows.ps1
```

产物在 `dist\IconMosaic\`，重命名 exe 后连同 `_internal` 一起分发。GitHub Actions 也会在推送 tag 时自动构建并上传产物，见 [`.github/workflows/build.yml`](.github/workflows/build.yml)。

## 常见问题

**便携版还要装 Python 吗？** 不用。便携版内嵌 Python 运行时与全部依赖，解压即用；只有源码版才需要 `Start.cmd` 安装环境。

**提示「当前密度需要 N 个不同图标」**：一帧的格子数超过素材库身份数。降低「密度」滑块，或用 `--build-library` 扩充素材。

**链接解析失败**：部分站点需要登录或限制访问，可先用浏览器下载，再导入本地文件。程序不会读取浏览器账号或 Cookie。

**导出很慢**：处理在 CPU 上完成，1080p 64 列约每秒 15–20 帧，10 分钟视频需要半小时左右。降低 `--height` 或 `--fps` 可以明显加速。

**HDR 素材**：当前输出为 SDR，HDR 视频请先转成 SDR 再导入。

## 许可

代码以 MIT 许可发布，见 [LICENSE](LICENSE)。第三方图标、品牌标志与随包依赖保留各自许可，商标归原权利人所有。
