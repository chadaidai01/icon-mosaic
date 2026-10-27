[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$NoLaunch,
    [switch]$Repair,
    [string]$PythonExe,
    [string]$RuntimeRoot
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$taskProject = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $taskProject '.runtime' }
$taskConfig = Get-Content -LiteralPath (Join-Path $taskProject 'bootstrap_config.json') -Raw | ConvertFrom-Json
$taskVenvPython = Join-Path $RuntimeRoot 'venv\Scripts\python.exe'
$taskManagedPython = Join-Path $RuntimeRoot 'python\python.exe'

function Test-TaskPython([string]$Candidate) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate)) { return $null }
    if ($Candidate -match '\\Microsoft\\WindowsApps\\') { return $null }
    try {
        $taskFound = & $Candidate -c 'import sys,struct; print(int((3,11)<=sys.version_info<(3,15) and struct.calcsize(chr(80))==8))' 2>$null
        if ($LASTEXITCODE -eq 0 -and ([string]$taskFound).Trim() -eq '1') { return [IO.Path]::GetFullPath($Candidate) }
    } catch { }
    return $null
}

function Find-TaskPython {
    $taskChoices = @($PythonExe, $taskVenvPython, $taskManagedPython)
    foreach ($taskName in @('python.exe','python3.exe')) {
        $taskCommand = Get-Command $taskName -ErrorAction SilentlyContinue
        if ($taskCommand) { $taskChoices += $taskCommand.Source }
    }
    if ($env:LOCALAPPDATA) {
        $taskLocations = Join-Path $env:LOCALAPPDATA 'Programs\Python'
        if (Test-Path -LiteralPath $taskLocations) {
            $taskChoices += Get-ChildItem -LiteralPath $taskLocations -Directory -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName 'python.exe' }
        }
    }
    foreach ($taskChoice in $taskChoices) {
        $taskValid = Test-TaskPython $taskChoice
        if ($taskValid) { return $taskValid }
    }
    return $null
}

function Read-TaskEnvironment([string]$Executable) {
    $taskData = & $Executable (Join-Path $taskProject 'environment_check.py') --json
    if ($LASTEXITCODE -ne 0) { throw '环境检查未完成。' }
    return ($taskData | ConvertFrom-Json)
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw '当前版本需要 64 位 Windows。' }
    $taskBasePython = Find-TaskPython
    if ($CheckOnly) {
        if ($taskBasePython) { Read-TaskEnvironment $taskBasePython | ConvertTo-Json -Depth 8 }
        else { @{ ready=$false; python=@{ ready=$false }; action='Run Start.cmd to install the local runtime.' } | ConvertTo-Json -Depth 8 }
        exit 0
    }

    foreach ($taskFolder in @($RuntimeRoot,(Join-Path $RuntimeRoot 'downloads'),(Join-Path $RuntimeRoot 'temp'),(Join-Path $RuntimeRoot 'pip-cache'))) {
        New-Item -ItemType Directory -Path $taskFolder -Force | Out-Null
    }
    $env:TEMP = Join-Path $RuntimeRoot 'temp'
    $env:TMP = $env:TEMP
    $env:PIP_CACHE_DIR = Join-Path $RuntimeRoot 'pip-cache'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    if (-not $taskBasePython) {
        Write-Host '没有找到适用的 Python，正在下载官方运行环境…'
        $taskInstaller = Join-Path $RuntimeRoot ('downloads\python-' + $taskConfig.python_version + '-amd64.exe')
        $taskHashOk = (Test-Path -LiteralPath $taskInstaller) -and ((Get-FileHash -LiteralPath $taskInstaller -Algorithm SHA256).Hash -eq $taskConfig.python_sha256)
        if (-not $taskHashOk) {
            Invoke-WebRequest -Uri $taskConfig.python_url -OutFile $taskInstaller -UseBasicParsing
        }
        if ((Get-FileHash -LiteralPath $taskInstaller -Algorithm SHA256).Hash -ne $taskConfig.python_sha256) { throw 'Python 安装器校验失败，请重试。' }
        $taskPythonDir = Join-Path $RuntimeRoot 'python'
        $taskInstallArgs = @('/quiet','InstallAllUsers=0','Include_pip=1','Include_tcltk=1','Include_test=0','Include_doc=0','Include_launcher=0','InstallLauncherAllUsers=0','AssociateFiles=0','Shortcuts=0','PrependPath=0','AppendPath=0',('TargetDir="'+$taskPythonDir+'"'))
        $taskInstallerProcess = Start-Process -FilePath $taskInstaller -ArgumentList $taskInstallArgs -WindowStyle Hidden -Wait -PassThru
        if ($taskInstallerProcess.ExitCode -notin @(0,3010)) { throw ('Python 安装失败，退出码：'+$taskInstallerProcess.ExitCode) }
        $taskBasePython = Test-TaskPython $taskManagedPython
        if (-not $taskBasePython) { throw 'Python 安装后未能通过检查。' }
    }

    if (-not (Test-TaskPython $taskVenvPython)) {
        Write-Host '正在创建独立运行环境…'
        & $taskBasePython -m venv (Join-Path $RuntimeRoot 'venv')
        if ($LASTEXITCODE -ne 0) { throw '创建独立运行环境失败。' }
    }
    $taskReport = Read-TaskEnvironment $taskVenvPython
    if (-not $taskReport.dependencies_ready -or $Repair) {
        Write-Host '正在安装或修复依赖，首次运行可能需要几分钟…'
        & $taskVenvPython -m pip install --disable-pip-version-check --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw 'pip 更新失败，请检查网络后重试。' }
        & $taskVenvPython -m pip install --disable-pip-version-check --upgrade -r (Join-Path $taskProject 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络后重试；再次运行会继续使用下载缓存。' }
        $taskReport = Read-TaskEnvironment $taskVenvPython
    }
    if (-not $taskReport.dependencies_ready) { throw '依赖检查仍未通过，请运行 Repair.cmd 并查看提示。' }
    if (-not $taskReport.library.ready) { throw '源码包缺少 assets/library.npz。请完整解压源码包，或从便携版复制图标库。' }
    $taskReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $RuntimeRoot 'environment.json') -Encoding UTF8
    Write-Host '环境已就绪。'
    if (-not $NoLaunch) {
        $taskPythonWindowless = Join-Path (Split-Path $taskVenvPython) 'pythonw.exe'
        if (-not (Test-Path -LiteralPath $taskPythonWindowless)) { $taskPythonWindowless = $taskVenvPython }
        Start-Process -FilePath $taskPythonWindowless -ArgumentList ('"'+(Join-Path $taskProject 'app.py')+'"') -WorkingDirectory $taskProject -WindowStyle Hidden
    }
} catch {
    Write-Host ('启动未完成：'+$_.Exception.Message) -ForegroundColor Red
    Write-Host '请保留窗口中的提示，检查网络后再次双击 Start.cmd。'
    exit 1
}
