$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot 'runtime\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = Join-Path $projectRoot '.venv-ocr\Scripts\python.exe'
}
$validationJob = Start-Job -ArgumentList $projectRoot, $pythonPath -ScriptBlock {
    param($root, $python)
    Set-Location -LiteralPath $root
    & $python -c "from paddle_ocr_engine.corrector import OllamaCorrector; OllamaCorrector.configure_environment(); c=OllamaCorrector(timeout=180); print(c.suggest('1. Presente el auxiliar contable del ejercicio 2025.','1')['suggested_text'])" 2>&1
}
$peakBytes = 0L
$peakPrivateBytes = 0L
$peakModelPrivateBytes = 0L
$peakProcesses = @()
while ($validationJob.State -in @('NotStarted', 'Running')) {
    $ollamaProcesses = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'ollama|llama' })
    $workingSet = ($ollamaProcesses | Measure-Object -Property WorkingSet64 -Sum).Sum
    $privateBytes = ($ollamaProcesses | Measure-Object -Property PrivateMemorySize64 -Sum).Sum
    $modelPrivateBytes = ($ollamaProcesses | Where-Object { $_.ProcessName -eq 'llama-server' } | Measure-Object -Property PrivateMemorySize64 -Sum).Sum
    if ($workingSet -gt $peakBytes) { $peakBytes = $workingSet; $peakProcesses = @($ollamaProcesses.ProcessName) }
    if ($privateBytes -gt $peakPrivateBytes) { $peakPrivateBytes = $privateBytes }
    if ($modelPrivateBytes -gt $peakModelPrivateBytes) { $peakModelPrivateBytes = $modelPrivateBytes }
    Start-Sleep -Milliseconds 250
    $validationJob = Get-Job -Id $validationJob.Id
}
$ErrorActionPreference = 'Continue'
$jobOutput = @(Receive-Job -Job $validationJob)
$ErrorActionPreference = 'Stop'
Remove-Job -Job $validationJob
[PSCustomObject]@{
    peak_bytes = $peakBytes
    peak_gib = [Math]::Round($peakBytes / 1GB, 3)
    peak_private_gib = [Math]::Round($peakPrivateBytes / 1GB, 3)
    model_peak_private_gib = [Math]::Round($peakModelPrivateBytes / 1GB, 3)
    processes = @($peakProcesses)
    budget_gib = 5
    within_budget = ($peakModelPrivateBytes -le 5GB)
    request_completed = ($validationJob.State -eq 'Completed')
    request_output = @($jobOutput | ForEach-Object { [string]$_ })
} | ConvertTo-Json
