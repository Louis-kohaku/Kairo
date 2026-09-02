param(
    [string]$VoiceId,
    [Parameter(Mandatory = $true)][string]$TextFile,
    [Parameter(Mandatory = $true)][string]$OutFile
)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

if ($VoiceId) {
    $match = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Id -eq $VoiceId } | Select-Object -First 1
    if ($match) {
        $synth.SelectVoice($match.VoiceInfo.Name)
    }
}

$text = Get-Content -LiteralPath $TextFile -Raw -Encoding UTF8
$synth.SetOutputToWaveFile($OutFile)
$synth.Speak($text)
$synth.Dispose()
