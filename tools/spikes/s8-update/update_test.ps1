# Spike S8: uji auto-update end-to-end secara lokal (Windows).
#
#   powershell -ExecutionPolicy Bypass -File tools\spikes\s8-update\update_test.ps1
#
# 1. Build A = v0.0.1 dengan cek update otomatis saat start (VITE_AUTO_UPDATE=1).
# 2. Build B = v0.0.2 (ditandatangani kunci updater dev) + latest.json.
# 3. Sajikan latest.json dan installer B dari http://127.0.0.1:8777 (hanya untuk uji lokal;
#    build rilis memakai HTTPS dan dangerousInsecureTransportProtocol=false).
# 4. Pasang A secara silent (per-user), jalankan, tunggu sampai aplikasi memperbarui diri ke v0.0.2.
# 5. Verifikasi dari log startup aplikasi, lalu uninstall dan bersihkan.

$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\..\.."
$app = "$root\apps\desktop"
$work = "$root\.data\s8"
$conf = "$app\src-tauri\tauri.conf.json"
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
$env:TAURI_SIGNING_PRIVATE_KEY = "$root\.data\keys\updater-dev.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = "recap-dev-only"
New-Item -ItemType Directory -Force $work | Out-Null

function Build-Version([string]$version, [string]$autoUpdate) {
    $json = Get-Content $conf -Raw
    $orig = $json
    Set-Content $conf ($json -replace '"version": "[^"]+"', "`"version`": `"$version`"") -Encoding utf8 -NoNewline
    try {
        $env:VITE_AUTO_UPDATE = $autoUpdate
        Push-Location $app
        # Lewat cmd: PowerShell 5.1 menganggap stderr program native (log info tauri) sebagai error.
        $out = cmd /c "npx tauri build 2>&1"
        $code = $LASTEXITCODE
        Pop-Location
        $out | Select-String -Pattern "error|Finished 1 bundle" | ForEach-Object { Write-Host $_.Line }
        if ($code -ne 0) { throw "build $version gagal (exit $code)" }
    } finally {
        Set-Content $conf $orig -Encoding utf8 -NoNewline
        Remove-Item Env:VITE_AUTO_UPDATE -ErrorAction SilentlyContinue
    }
    $setup = "$root\target\release\bundle\nsis\Recap Dev_${version}_x64-setup.exe"
    Copy-Item $setup "$work\" -Force
    Copy-Item "$setup.sig" "$work\" -Force
}

Write-Host "== build A (0.0.1, auto-update) dan B (0.0.2)"
Build-Version "0.0.1" "1"
Build-Version "0.0.2" "0"

$sig = Get-Content "$work\Recap Dev_0.0.2_x64-setup.exe.sig" -Raw
$latest = @{
    version   = "0.0.2"
    notes     = "Uji update lokal spike S8"
    pub_date  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    platforms = @{ "windows-x86_64" = @{ signature = $sig.Trim(); url = "http://127.0.0.1:8777/Recap%20Dev_0.0.2_x64-setup.exe" } }
} | ConvertTo-Json -Depth 5
Set-Content "$work\latest.json" $latest -Encoding utf8

$server = Start-Process -FilePath python -ArgumentList "-m", "http.server", "8777", "--bind", "127.0.0.1", "--directory", "`"$work`"" -PassThru -WindowStyle Hidden
try {
    $installDir = "$env:LOCALAPPDATA\Recap Dev"
    $log = "$env:LOCALAPPDATA\id.recap.dev\logs\startup.jsonl"
    Remove-Item $log -ErrorAction SilentlyContinue
    Write-Host "== pasang A (silent, per-user)"
    Start-Process "$work\Recap Dev_0.0.1_x64-setup.exe" -ArgumentList "/S" -Wait
    $exe = Get-ChildItem $installDir -Filter "*.exe" | Where-Object { $_.Name -notlike "uninstall*" } | Select-Object -First 1
    Write-Host "terpasang: $($exe.FullName) ($((Get-Item $exe.FullName).VersionInfo.ProductVersion))"
    Write-Host "== jalankan A; aplikasi harus memperbarui diri ke 0.0.2"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Start-Process $exe.FullName
    $ok = $false
    while ($sw.Elapsed.TotalSeconds -lt 120) {
        Start-Sleep 2
        if ((Test-Path $log) -and (Select-String -Path $log -Pattern '"version":"0.0.2"' -Quiet)) { $ok = $true; break }
    }
    Write-Host ("== hasil: {0} dalam {1:N0} s" -f ($(if ($ok) { "LULUS: v0.0.2 berjalan setelah update otomatis" } else { "GAGAL: v0.0.2 tidak terdeteksi" }), $sw.Elapsed.TotalSeconds))
    if (Test-Path $log) { Get-Content $log }
    $ver = (Get-Item $exe.FullName).VersionInfo.ProductVersion
    Write-Host "versi exe terpasang sekarang: $ver"
    Get-Process | Where-Object { $_.Path -like "$installDir*" } | Select-Object Name, Id, Path | Format-Table -AutoSize | Out-String | Write-Host
} finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    Get-Process | Where-Object { $_.Path -like "$env:LOCALAPPDATA\Recap Dev*" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep 1
    $un = "$env:LOCALAPPDATA\Recap Dev\uninstall.exe"
    if (Test-Path $un) { Start-Process $un -ArgumentList "/S" -Wait; Write-Host "== uninstall selesai" }
}
