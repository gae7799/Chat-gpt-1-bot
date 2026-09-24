$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Chiudi il bot. Seleziona Bot-Foto, contenente AVVIA.bat, FOTO e DATI.'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 1 }
$target = $dialog.SelectedPath
foreach ($name in @('bot.py','AVVIA.bat','FOTO','DATI','direttore_autonomo.py','fourthwall_api.py','registro.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $target $name))) {
        [System.Windows.Forms.MessageBox]::Show('Cartella non valida. Nessuna modifica.') | Out-Null
        exit 2
    }
}
# Refuse to replace code while a known bot process uses this folder.
$running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -and
    $_.CommandLine.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
    $_.CommandLine -match '(bot|avvia_bot)\.py'
})
if ($running.Count -gt 0) {
    [System.Windows.Forms.MessageBox]::Show('Chiudi il bot e la finestra AVVIA.bat prima di aggiornare.') | Out-Null
    exit 4
}
$payload = Join-Path $PSScriptRoot 'NUOVI_FILE'
$backup = Join-Path $target ('BACKUP-PRE-2.0.0-' + [guid]::NewGuid().ToString('N'))
$changed = @()
try {
    $files = @(Get-ChildItem -LiteralPath $payload -File | Where-Object { $_.Name -notlike 'test_*.py' })
    if ($files.Count -eq 0) { throw 'Pacchetto vuoto' }
    New-Item -ItemType Directory -Path $backup | Out-Null
    # Complete all backups before overwriting any program file.
    foreach ($file in $files) {
        $old = Join-Path $target $file.Name
        if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination $backup }
    }
    foreach ($file in $files) {
        $changed += $file.Name
        $destination = Join-Path $target $file.Name
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
        if ((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash) {
            throw ('Verifica del file non riuscita: ' + $file.Name)
        }
    }
    [System.Windows.Forms.MessageBox]::Show('Aggiornamento 2.0.0 completato. FOTO, DATI, piano e credenziali conservati. Riapri AVVIA.bat.') | Out-Null
} catch {
    $recovered = $true
    foreach ($name in $changed) {
        try {
            $saved = Join-Path $backup $name
            $destination = Join-Path $target $name
            if (Test-Path -LiteralPath $saved) {
                Copy-Item -LiteralPath $saved -Destination $destination -Force
            } elseif (Test-Path -LiteralPath $destination) {
                Remove-Item -LiteralPath $destination
            }
        } catch { $recovered = $false }
    }
    $message = if ($recovered) { 'Installazione non riuscita. File precedenti conservati o ripristinati.' } else { 'Installazione non riuscita. Ripristino incompleto: non avviare il bot. Conserva il backup e chiedi assistenza.' }
    [System.Windows.Forms.MessageBox]::Show($message + "`nBackup: " + $backup) | Out-Null
    exit 3
}
