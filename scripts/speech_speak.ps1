# Windows Native Offline Text-to-Speech via SAPI
param([string]$text)
if (-not $text) { exit 0 }
try {
    # Sanitize text for speech (strip markdown backticks and brackets)
    $clean = $text -replace '[`*_#\[\]\(\)]', ' '
    if ($clean.Length -gt 250) { $clean = $clean.Substring(0, 250) }
    $voice = New-Object -ComObject SAPI.SpVoice
    $voice.Rate = 1
    $voice.Volume = 100
    # Prefer female voice (Microsoft Zira / Hazel)
    $femaleVoice = $voice.GetVoices() | Where-Object { $_.GetDescription() -match 'Zira|Hazel|Female|Eva|Susan|Jenny' } | Select-Object -First 1
    if ($femaleVoice) {
        $voice.Voice = $femaleVoice
    }
    [void]$voice.Speak($clean, 1) # 1 = SVSFlagsAsync (non-blocking)
} catch {}

