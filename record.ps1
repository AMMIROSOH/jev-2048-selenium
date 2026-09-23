param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ExtraArgs
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "The local virtual environment is missing: $python"
}
if (-not $env:TYPESAFE_API_KEY) {
    throw 'Set $env:TYPESAFE_API_KEY before starting a Jev recording.'
}

& $python "run.py" "--record" @ExtraArgs
exit $LASTEXITCODE

