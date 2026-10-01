# Gera o instalador localmente e publica o release no GitHub (manual, sem
# GitHub Actions). O app consulta os releases deste repositorio para se
# atualizar (libs/updater.py -> UPDATE_REPO).
#
# Antes: subir __version_info__ em libs/__init__.py, commitar, criar a tag e
# enviar:
#   git tag -a v1.9.1 -m "Novidades desta versao"
#   git push origin main v1.9.1
# Depois:
#   powershell -ExecutionPolicy Bypass -File .\publish_release.ps1
#   (-SkipBuild reaproveita o instalador ja gerado em installer\Output)
#
# Autenticacao: usa a mesma credencial do GitHub que o "git push" usa
# (Git Credential Manager). O token nao e exibido nem gravado.
# (arquivo mantido em ASCII de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI)

param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo = "FialhoTKL/labelImg-master"

$match = Select-String -Path "libs\__init__.py" -Pattern "^__version_info__\s*=\s*\(([^)]+)\)"
if (-not $match) { throw "__version_info__ nao encontrado em libs\__init__.py" }
$version = ($match.Matches[0].Groups[1].Value -replace "[\s'`"]", "") -replace ",", "."
$tag = "v$version"
Write-Host "Versao: $version (tag $tag)"

# A tag precisa existir no GitHub (o release e criado a partir dela).
$remoteTag = git ls-remote --tags origin "refs/tags/$tag"
if (-not $remoteTag) {
    throw "A tag $tag nao existe no GitHub. Crie e envie: git tag -a $tag -m ""..."" ; git push origin main $tag"
}

if (-not $SkipBuild) {
    & powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
    if ($LASTEXITCODE -ne 0) { throw "Build falhou" }
}

$setupName = "LabelImg_Setup_$version.exe"
$files = @("installer\Output\$setupName", "installer\Output\$setupName.sha256")
foreach ($f in $files) { if (-not (Test-Path $f)) { throw "Arquivo nao encontrado: $f" } }

# Token da credencial do git para github.com
# (entrada via arquivo + redirecionamento do cmd: o pipe do PowerShell 5.1
# altera o texto e o git recusa com "missing protocol field")
$credIn = [IO.Path]::GetTempFileName()
[IO.File]::WriteAllText($credIn, "protocol=https`nhost=github.com`n`n", (New-Object Text.UTF8Encoding $false))
try { $cred = cmd /c "git credential fill < `"$credIn`"" } finally { Remove-Item $credIn }
$token = $cred | Where-Object { $_ -like "password=*" } | Select-Object -First 1
if ($token) { $token = $token.Substring(9).Trim() }
if (-not $token) { throw "Credencial do GitHub nao encontrada (faca um git push antes para autenticar)." }

$headers = @{
    Authorization          = "Bearer $token"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "labelimg-publish"
}

# Notas do release = mensagem da tag
$notes = (git tag -l --format='%(contents)' $tag) -join "`n"
if (-not $notes.Trim()) { $notes = "LabelImg $version" }

$release = $null
try {
    $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$repo/releases/tags/$tag"
    Write-Host "Release $tag ja existe; atualizando os arquivos."
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
}

if (-not $release) {
    $body = @{ tag_name = $tag; name = "LabelImg $version"; body = $notes; draft = $false; prerelease = $false } | ConvertTo-Json
    $release = Invoke-RestMethod -Method Post -Headers $headers -ContentType "application/json; charset=utf-8" `
        -Uri "https://api.github.com/repos/$repo/releases" -Body ([Text.Encoding]::UTF8.GetBytes($body))
    Write-Host "Release $tag criado."
}

$uploadBase = $release.upload_url -replace "\{.*\}$", ""
foreach ($f in $files) {
    $name = Split-Path $f -Leaf
    $existing = $release.assets | Where-Object { $_.name -eq $name }
    if ($existing) {
        Invoke-RestMethod -Method Delete -Headers $headers -Uri $existing.url | Out-Null
    }
    Write-Host "Enviando $name..."
    Invoke-RestMethod -Method Post -Headers $headers -ContentType "application/octet-stream" `
        -Uri "$uploadBase`?name=$([Uri]::EscapeDataString($name))" -InFile $f | Out-Null
}

Write-Host "`nPublicado: $($release.html_url)"
