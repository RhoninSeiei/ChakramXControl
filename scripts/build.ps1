param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
$pythonExe = (Get-Command $Python -CommandType Application | Select-Object -First 1).Source
$project = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $project
try {
    & $pythonExe -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }

    $dist = Join-Path $project 'dist'
    New-Item -ItemType Directory -Force -Path $dist | Out-Null
    $notices = Join-Path $dist 'THIRD_PARTY_NOTICES.txt'
    & $pythonExe scripts/collect_notices.py --output $notices
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $notices)) {
        throw 'Could not collect the third-party notices.'
    }

    & $pythonExe -m PyInstaller --noconfirm --clean --onefile --windowed --noupx `
        --name ChakramXControl --icon assets/chakram-x.ico --copy-metadata hidapi `
        --add-data 'assets/chakram-x.ico:assets' --add-data 'LICENSE:.' `
        --add-data "${notices};." app.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

    $exe = Join-Path $dist 'ChakramXControl.exe'
    $smoke = Start-Process -FilePath $exe -ArgumentList '--smoke-test' -WorkingDirectory $dist -WindowStyle Hidden -PassThru
    if (!$smoke.WaitForExit(60000)) {
        $smoke.Kill($true)
        throw 'Packaged application startup timed out.'
    }
    if ($smoke.ExitCode -ne 0) { throw "Startup test failed with exit code $($smoke.ExitCode)." }

    $lines = foreach ($file in @($exe, $notices)) {
        $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $([IO.Path]::GetFileName($file))"
    }
    [IO.File]::WriteAllText((Join-Path $dist 'SHA256SUMS.txt'), ($lines -join "`n") + "`n", [Text.Encoding]::ASCII)
} finally {
    Pop-Location
}
