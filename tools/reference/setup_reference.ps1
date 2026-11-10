param(
    [string]$Python = "python",
    [switch]$ShareInstalledPackages
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "../..")).Path
$venvPath = Join-Path $projectRoot ".venv-reference"
$runtimePath = Join-Path $projectRoot ".runtime/reference"
New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts/python.exe"))) {
    $venvArgs = @("-m", "venv")
    if ($ShareInstalledPackages) {
        $venvArgs += "--system-site-packages"
    }
    & $Python @venvArgs $venvPath
    if ($LASTEXITCODE -ne 0) { throw "Creating the isolated reference environment failed." }
}
$referencePython = Join-Path $venvPath "Scripts/python.exe"
& $referencePython -m pip install --only-binary=:all: `
    --cache-dir (Join-Path $runtimePath "pip-cache") `
    --report (Join-Path $runtimePath "install-report.json") `
    -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Installing the pinned reference dependencies failed." }
Write-Output "Reference Python: $referencePython"
Write-Output "Global Python packages were not modified."
