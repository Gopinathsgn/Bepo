<#
.SYNOPSIS
  Packs the PyInstaller output (dist\Bepo) into an MSIX for the Microsoft Store.

.DESCRIPTION
  Run after build.bat (or the PyInstaller + model steps in release.yml). The package is NOT signed: Partner
  Center signs it with Microsoft's certificate on submission. An unsigned .msix cannot be double-click installed;
  to try one locally, sign a copy with a self-signed certificate whose subject equals -Publisher.

  Identity values come from Partner Center > Product management > Product identity. They can be passed as
  parameters or through the environment variables MSIX_IDENTITY_NAME, MSIX_PUBLISHER and
  MSIX_PUBLISHER_DISPLAY_NAME (the release workflow reads them from repository variables).

.EXAMPLE
  .\packaging\msix\build_msix.ps1 -Version 1.2.1 -IdentityName 12345Gopinath.Bepo -Publisher "CN=ABCD1234-..." -PublisherDisplayName Gopinath
#>
param(
    [Parameter(Mandatory = $true)] [string] $Version,                  # x.y.z (version.py)
    [string] $IdentityName = $env:MSIX_IDENTITY_NAME,
    [string] $Publisher = $env:MSIX_PUBLISHER,
    [string] $PublisherDisplayName = $env:MSIX_PUBLISHER_DISPLAY_NAME,
    [string] $SourceDir = 'dist\Bepo',
    [string] $OutFile = '',
    [switch] $LayoutOnly                                               # build the folder, skip makeappx (no SDK needed)
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root

if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
    throw "Version '$Version' must look like 1.2.3 (version.py)."
}
$msixVersion = "$Version.0"        # the Store reserves the last part: it must be 0

if (-not $IdentityName -or -not $Publisher -or -not $PublisherDisplayName) {
    Write-Warning 'No Partner Center identity given: using placeholders. The package is fine for a local layout check but the Store will reject it.'
    if (-not $IdentityName) { $IdentityName = 'Gopinath.Bepo' }
    if (-not $Publisher) { $Publisher = 'CN=Gopinath' }
    if (-not $PublisherDisplayName) { $PublisherDisplayName = 'Gopinath' }
}
if (-not (Test-Path (Join-Path $SourceDir 'Bepo.exe'))) {
    throw "$SourceDir\Bepo.exe not found. Build the app first (build.bat)."
}
if (-not $OutFile) { $OutFile = "dist\Bepo-Store-v$Version.msix" }

# 1. layout = app files + manifest + images
$layout = Join-Path $root 'build\msix\layout'
if (Test-Path $layout) { Remove-Item $layout -Recurse -Force }
New-Item -ItemType Directory -Path $layout | Out-Null
Copy-Item (Join-Path $SourceDir '*') -Destination $layout -Recurse

python (Join-Path $PSScriptRoot 'make_assets.py') (Join-Path $layout 'Assets')
if ($LASTEXITCODE -ne 0) { throw 'Could not generate the package images.' }

$manifest = Get-Content (Join-Path $PSScriptRoot 'AppxManifest.xml.in') -Raw -Encoding UTF8
$esc = { param($s) [System.Security.SecurityElement]::Escape($s) }
$manifest = $manifest.Replace('@IDENTITY_NAME@', (& $esc $IdentityName)).
    Replace('@PUBLISHER@', (& $esc $Publisher)).
    Replace('@PUBLISHER_DISPLAY_NAME@', (& $esc $PublisherDisplayName)).
    Replace('@VERSION@', $msixVersion)
[xml]$null = $manifest             # fail early on malformed XML
[System.IO.File]::WriteAllText((Join-Path $layout 'AppxManifest.xml'), $manifest, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Layout ready: $layout (package version $msixVersion)"
if ($LayoutOnly) { return }

# 2. makeappx.exe ships with the Windows 10/11 SDK (preinstalled on GitHub's windows-latest runners)
$makeappx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" -ErrorAction SilentlyContinue |
    Sort-Object { [version]($_.Directory.Parent.Name) } -Descending | Select-Object -First 1
if (-not $makeappx) { throw 'makeappx.exe not found. Install the Windows 10/11 SDK.' }

$out = Join-Path $root $OutFile
New-Item -ItemType Directory -Path (Split-Path $out) -Force | Out-Null
if (Test-Path $out) { Remove-Item $out -Force }
& $makeappx.FullName pack /d $layout /p $out /o
if ($LASTEXITCODE -ne 0) { throw 'makeappx failed.' }
Write-Host ("Created {0} ({1:N0} MB)" -f $OutFile, ((Get-Item $out).Length / 1MB))
