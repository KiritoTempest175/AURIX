# Windows Native Offline Speech-to-Text via System.Speech
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    Add-Type -AssemblyName System.Speech
    $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    $rec.SetInputToDefaultAudioDevice()

    # Free-form dictation grammar
    $dictation = New-Object System.Speech.Recognition.DictationGrammar
    $dictation.Name = "Dictation"
    $rec.LoadGrammar($dictation)

    # Listen for spoken phrase
    $res = $rec.Recognize([TimeSpan]::FromSeconds(6))
    if ($res -and $res.Text -and ($res.Text.Trim().Length -gt 0)) {
        Write-Output "SPEECH_RESULT:$($res.Text.Trim())"
    } else {
        Write-Output "SPEECH_RESULT:"
    }
    $rec.Dispose()
} catch {
    Write-Output "SPEECH_RESULT:"
}
