$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "找不到 Python Launcher。請先安裝 Python 3.12，並勾選 Add Python to PATH。"
}

if (-not (Test-Path ".venv")) {
    py -3.12 -m venv .venv
}

$Python = Join-Path (Resolve-Path ".venv") "Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install ".[dev]"
& $Python -m pytest
& $Python -m PyInstaller --clean --noconfirm SmartDocumentOrganizer.spec

Write-Host ""
Write-Host "Windows 應用已建立：dist\SmartDocumentOrganizer\SmartDocumentOrganizer.exe" -ForegroundColor Green
Write-Host "若已安裝 Inno Setup，可再編譯 installer\SmartDocumentOrganizer.iss 產生安裝程式。"
