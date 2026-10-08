# User-local Windows x64 installation; no Python or administrator privileges required.
param([string]$Version = 'latest')
$ErrorActionPreference = 'Stop'
if ($Version -eq 'latest') {
    $api = if ($env:NETMED_RELEASE_API_URL) { $env:NETMED_RELEASE_API_URL } else { 'https://api.github.com/repos/lspindler2509/Network-Medicine-For-Agents/releases?per_page=1' }
    if ($api -match '^file://') {
        $releases = Get-Content ([uri]$api).LocalPath -Raw | ConvertFrom-Json
    } else {
        if ($api -notmatch '^https://') { throw 'Release discovery requires HTTPS.' }
        $releases = Invoke-RestMethod $api
    }
    $release = $releases | Where-Object { -not $_.draft } | Select-Object -First 1
    $version = $release.tag_name
    if (-not $version) { throw 'No published release found; use -Version to select a version.' }
}
if ($version -notmatch '^v[0-9][a-zA-Z0-9._-]*$') { throw 'Invalid release version' }
$architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($env:OS -ne 'Windows_NT' -or $architecture -ne 'X64') { throw 'This installer supports x64 Windows only.' }
$root = if ($env:NETMED_INSTALL_DIR) { $env:NETMED_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'Programs\netmed' }
$base = if ($env:NETMED_RELEASE_BASE_URL) { $env:NETMED_RELEASE_BASE_URL } else { "https://github.com/lspindler2509/Network-Medicine-For-Agents/releases/download/$version" }
New-Item -ItemType Directory -Force -Path $root | Out-Null
$lockPath = Join-Path $root '.install-lock'
$lock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
$temp = Join-Path $root ('.install-' + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $temp | Out-Null
    $archive = 'netmed-windows-amd64.zip'
    $zip = Join-Path $temp $archive
    if ($base -match '^file://') {
        $local = ([uri]$base).LocalPath
        Copy-Item (Join-Path $local $archive) $zip
        $checksum = Get-Content (Join-Path $local "$archive.sha256") -Raw
    } else {
        if ($base -notmatch '^https://') { throw 'Release download requires HTTPS.' }
        Invoke-WebRequest -UseBasicParsing "$base/$archive" -OutFile $zip
        $checksum = (Invoke-WebRequest -UseBasicParsing "$base/$archive.sha256").Content
    }
    $expected = ($checksum.Trim() -split '\s+')[0]
    # Use .NET directly, independent of PowerShell's optional hash/archive commands.
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($zip)
    try {
        $actual = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
    if ($actual -ne $expected) { throw 'Checksum mismatch; installation unchanged.' }
    # Add-Type resolves the framework assembly name in Windows PowerShell 5.1
    # as well as PowerShell 7; Assembly.Load with a short name does not.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $temp)
    if (-not (Test-Path (Join-Path $temp 'netmed\netmed.exe'))) { throw 'Archive does not contain netmed.exe.' }
    $destination = Join-Path $root $version
    if (Test-Path $destination) { throw "Already installed: $destination. Stop its jobs and remove it to reinstall." }
    Move-Item (Join-Path $temp 'netmed') $destination
    if ($env:NETMED_MODIFY_PATH -ne '0') {
        $old = [Environment]::GetEnvironmentVariable('Path', 'User')
        $entries = @($old -split ';' | Where-Object { $_ -and -not $_.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) })
        $updated = (@($destination) + $entries) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
        $env:PATH = "$destination;$env:PATH"
    }
    Write-Host "Installed $version at $destination"
    Write-Host 'Restart your terminal/agent to pick up PATH, then run: netmed --help'
} finally {
    Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
    $lock.Dispose()
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
}
