# ============================================================
#  EC-Tok — genera el instalador de Windows
#  Lo corre GitHub Actions (ver .github/workflows/windows-installer.yml).
#  A mano: Python 3.12 + PyInstaller + TikTokLive + Inno Setup 6, y:
#    powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
#  Resultado: windows\out\EC-Tok-Setup-<versión>.exe
# ============================================================
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir '..')).Path
$srcRoot     = Join-Path $projectRoot 'src'

function Invoke-Checked([string]$FilePath, [string[]]$ArgumentList = @()) {
  & $FilePath @ArgumentList
  if ($LASTEXITCODE -ne 0) { throw "$FilePath terminó con código $LASTEXITCODE" }
}

$version = (Select-String -Path (Join-Path $srcRoot 'ectok_server.py') -Pattern '^APP_VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "EC-Tok $version" -ForegroundColor Cyan

$distDir = Join-Path $scriptDir 'dist'
$outDir  = Join-Path $scriptDir 'out'
$appDir  = Join-Path $distDir 'ectok'
New-Item -ItemType Directory -Force -Path $distDir, $outDir | Out-Null

# --- Fecha de publicación (hora de Ciudad de México) ---
try { $tz = [TimeZoneInfo]::FindSystemTimeZoneById('Central Standard Time (Mexico)') } catch { $tz = [TimeZoneInfo]::Local }
$buildDate = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $tz).ToString('yyyy-MM-dd HH:mm')
Set-Content -Path (Join-Path $srcRoot 'ectok_build.py') -Value "BUILD_DATE = `"$buildDate`"" -Encoding ascii

# --- Programa (PyInstaller, carpeta, sin consola) ---
Write-Host 'Compilando EC-Tok...'
Invoke-Checked 'python' @(
  '-m', 'PyInstaller', '--clean', '--noconfirm', '--onedir', '--noconsole',
  '--name', 'ectok',
  '--icon', (Join-Path $srcRoot 'web\img\ectok.ico'),
  '--add-data', "$(Join-Path $srcRoot 'web');web",
  '--paths', $srcRoot,
  '--hidden-import', 'ectok_build',
  '--hidden-import', 'ectok_update',
  '--hidden-import', 'ectok_live',
  '--collect-all', 'TikTokLive',
  '--exclude-module', 'tkinter',
  '--distpath', $distDir,
  '--workpath', (Join-Path $scriptDir '.build'),
  '--specpath', (Join-Path $scriptDir '.build'),
  (Join-Path $srcRoot 'ectok_server.py')
)

# --- FFmpeg: para convertir las animaciones especiales que sube el streamer ---
Write-Host 'Descargando FFmpeg...'
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("ectok-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile (Join-Path $tmp 'f.zip')
Expand-Archive -Path (Join-Path $tmp 'f.zip') -DestinationPath (Join-Path $tmp 'x') -Force
$ff = Get-ChildItem -Path (Join-Path $tmp 'x') -Filter 'ffmpeg.exe' -Recurse | Select-Object -First 1
if (-not $ff) { throw 'No se encontró ffmpeg.exe en el zip de FFmpeg.' }
New-Item -ItemType Directory -Force -Path (Join-Path $appDir 'bin') | Out-Null
Copy-Item $ff.FullName (Join-Path $appDir 'bin\ffmpeg.exe') -Force
& (Join-Path $appDir 'bin\ffmpeg.exe') -hide_banner -encoders | Select-String 'libx264|libwebp_anim|libvpx-vp9' | ForEach-Object { Write-Host $_.Line.Trim() }

# Prueba rápida: que el programa arranque y conteste (sin abrir ventana).
$exe = Join-Path $appDir 'ectok.exe'
$p = Start-Process -FilePath $exe -ArgumentList '--no-browser', '--stay', '--port', '8799' -PassThru
try {
  $ok = $false
  for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
    Start-Sleep -Seconds 1
    try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8799/api/info' -TimeoutSec 3; $ok = $r.version -eq $version } catch {}
  }
  if (-not $ok) { throw 'ectok.exe no arrancó.' }
  Write-Host "ectok.exe contesta (versión $version)"
} finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }

# --- Instalador ---
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Falta Inno Setup 6.' }
Invoke-Checked $iscc @("/DAppVersion=$version", "/DSourceDir=$appDir", "/O$outDir", (Join-Path $scriptDir 'ectok.iss'))
Write-Host "Listo: $outDir\EC-Tok-Setup-$version.exe" -ForegroundColor Green
