# Flight Scout 启动脚本
#   .\run.ps1                    启动网页仪表盘 (http://127.0.0.1:8777)
#   .\run.ps1 -Port 9000         换端口
#   .\run.ps1 -Python C:\py\python.exe   指定解释器
param(
    [int]$Port = 8777,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-Python {
    $names = @("python", "python3", "py")
    foreach ($name in $names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    $globs = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "$env:USERPROFILE\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
    )
    foreach ($pattern in $globs) {
        $hit = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return ""
}

if (-not $Python) { $Python = Find-Python }
if (-not $Python) {
    Write-Host "未找到 Python 3.10+。请安装后重试，或指定：.\run.ps1 -Python C:\path\to\python.exe" -ForegroundColor Red
    exit 1
}

Write-Host "使用 Python: $Python" -ForegroundColor DarkGray
& $Python "$root\flightscout.py" serve --port $Port
