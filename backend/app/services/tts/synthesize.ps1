param(
    [string]$VoiceId,
    [Parameter(Mandatory = $true)][string]$TextFile,
    [Parameter(Mandatory = $true)][string]$OutFile,
    # SAPI speaking rate, -10 (slowest) to 10 (fastest). 0 is the voice's
    # own default and is what every caller got before the edit director
    # started choosing a delivery per video.
    [int]$Rate = 0
)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

if ($VoiceId) {
    $match = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Id -eq $VoiceId } | Select-Object -First 1
    if ($match) {
        $synth.SelectVoice($match.VoiceInfo.Name)
    }
}

if ($Rate -ne 0) {
    # Clamped here as well as by the caller: SAPI throws on a value outside
    # -10..10, and a failed synthesis would silence the whole scene.
    $synth.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
}

$text = Get-Content -LiteralPath $TextFile -Raw -Encoding UTF8
$synth.SetOutputToWaveFile($OutFile)
$synth.Speak($text)
$synth.Dispose()
