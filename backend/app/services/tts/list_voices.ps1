param()
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
    $v = $_.VoiceInfo
    [PSCustomObject]@{
        id      = $v.Id
        name    = $v.Name
        culture = $v.Culture.Name
        gender  = $v.Gender.ToString()
    }
}
$synth.Dispose()
if ($null -eq $voices) {
    Write-Output "[]"
} else {
    ConvertTo-Json -InputObject @($voices) -Compress
}
