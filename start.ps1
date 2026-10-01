param([switch]$Mobile)
Set-Location -LiteralPath $PSScriptRoot
if ($Mobile) { python app.py --host 0.0.0.0 } else { python app.py }
