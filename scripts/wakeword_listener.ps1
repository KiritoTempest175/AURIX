# Continuous Offline Wake-Word Detection for "Hey Luna" / "Luna" / "Aurix" / "Wake Up"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    Add-Type -AssemblyName System.Speech
    $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    $rec.SetInputToDefaultAudioDevice()

    $choices = New-Object System.Speech.Recognition.Choices
    $choices.Add([string[]]@("luna", "hey luna", "aurix", "wake up", "hello luna", "call luna"))

    $builder = New-Object System.Speech.Recognition.GrammarBuilder
    $builder.Append($choices)

    $grammar = New-Object System.Speech.Recognition.Grammar($builder)
    $grammar.Name = "WakeWordGrammar"
    $rec.LoadGrammar($grammar)

    while ($true) {
        $res = $rec.Recognize()
        if ($res -and $res.Text) {
            $t = $res.Text.Trim().ToLower()
            if ($t.Length -gt 0) {
                Write-Output "WAKEWORD_DETECTED:$t"
                [Console]::Out.Flush()
            }
        }
    }
} catch {
    # Exit if audio device unavailable
}
