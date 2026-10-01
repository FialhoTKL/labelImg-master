# Gera o instalador do LabelImg localmente (para testes).
# Para gerar e publicar o release no GitHub use publish_release.ps1.
#
# Uso (na raiz do projeto, com o venv criado):
#   powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
#
# Requer o Inno Setup 6:  winget install JRSoftware.InnoSetup
# (arquivo mantido em ASCII de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Versao: fonte unica em libs/__init__.py
$match = Select-String -Path "libs\__init__.py" -Pattern "^__version_info__\s*=\s*\(([^)]+)\)"
if (-not $match) { throw "__version_info__ nao encontrado em libs\__init__.py" }
$version = ($match.Matches[0].Groups[1].Value -replace "[\s'`"]", "") -replace ",", "."
Write-Host "Versao: $version"

# Python do venv, se existir
$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "`n== Recursos Qt (pyrcc5) =="
& $python -m PyQt5.pyrcc_main -o libs\resources.py resources.qrc
if ($LASTEXITCODE -ne 0) { throw "pyrcc5 falhou" }

Write-Host "`n== PyInstaller =="
& $python -m PyInstaller labelImg.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

Write-Host "`n== Inno Setup =="
$candidatos = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $candidatos | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}
if (-not $iscc) {
    throw "ISCC.exe nao encontrado. Instale o Inno Setup 6: winget install JRSoftware.InnoSetup"
}

& $iscc "/DMyAppVersion=$version" "installer\labelimg.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou" }

$setup = "installer\Output\LabelImg_Setup_$version.exe"
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
"$hash  LabelImg_Setup_$version.exe" | Out-File -Encoding ascii "$setup.sha256"

Write-Host "`nPronto: $setup"
Write-Host "SHA-256: $hash"
