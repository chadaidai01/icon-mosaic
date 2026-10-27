[CmdletBinding()]
param([string]$PythonExe)
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskPython = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $taskProject '.runtime\venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $taskPython)) {
    & (Join-Path $taskProject 'bootstrap.ps1') -NoLaunch
    if ($LASTEXITCODE -ne 0) { throw '运行环境准备失败。' }
}
$taskBuildTemp = Join-Path $taskProject 'work\build\temp'
New-Item -ItemType Directory -Path $taskBuildTemp -Force | Out-Null
$env:TEMP = $taskBuildTemp
$env:TMP = $taskBuildTemp
$env:PIP_CACHE_DIR = Join-Path $taskProject 'work\build\pip-cache'
& $taskPython -m pip install --disable-pip-version-check -r (Join-Path $taskProject 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw '构建依赖安装失败。' }
& $taskPython (Join-Path $taskProject 'prepare_build.py')
if ($LASTEXITCODE -ne 0) { throw '构建资源准备失败。' }
$taskBuildDir = Join-Path $taskProject 'work\build'
$taskDistDir = Join-Path $taskProject 'dist'
$taskProjectPrefix = [IO.Path]::GetFullPath($taskProject).TrimEnd('\') + '\'
if (-not [IO.Path]::GetFullPath($taskDistDir).StartsWith($taskProjectPrefix,[StringComparison]::OrdinalIgnoreCase)) { throw '输出目录不在项目内。' }
$env:PYINSTALLER_CONFIG_DIR = Join-Path $taskBuildDir 'cache'
$taskArgs = @(
    '-m','PyInstaller','--noconfirm','--windowed','--name','IconMosaic',
    '--distpath',$taskDistDir,'--workpath',$taskBuildDir,'--specpath',$taskBuildDir,
    '--add-data',((Join-Path $taskProject 'assets')+';assets'),
    '--add-data',((Join-Path $taskProject 'licenses')+';licenses'),
    '--add-binary',((Join-Path $taskProject 'bin\ffmpeg.exe')+';bin'),
    '--icon',(Join-Path $taskProject 'assets\app.ico'),
    '--collect-all','yt_dlp',
    '--exclude-module','imageio_ffmpeg','--exclude-module','matplotlib','--exclude-module','pandas',
    '--exclude-module','pytest','--exclude-module','IPython','--exclude-module','scipy',
    '--exclude-module','PyQt5','--exclude-module','PySide6','--exclude-module','torch',
    (Join-Path $taskProject 'app.py')
)
& $taskPython @taskArgs
if ($LASTEXITCODE -ne 0) { throw 'Windows 打包失败。' }
$taskPortableDir = Join-Path $taskDistDir 'IconMosaic'
Rename-Item -LiteralPath (Join-Path $taskPortableDir 'IconMosaic.exe') -NewName '图标映像.exe'
Copy-Item -LiteralPath (Join-Path $taskProject 'README.md') -Destination (Join-Path $taskPortableDir '使用说明.md')
Write-Host ('打包完成：'+$taskPortableDir)
