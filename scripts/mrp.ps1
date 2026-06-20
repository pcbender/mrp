$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
python (Join-Path $ScriptDir 'mrp') @args
exit $LASTEXITCODE
