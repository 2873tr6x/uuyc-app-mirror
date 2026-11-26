param([string]$Source = 'D:\uuyc_windows_untrusted', [string]$Output = 'dist/windows-hints.json')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security.Cryptography.Pkcs
$rows = foreach ($file in Get-ChildItem -LiteralPath $Source -Filter '*.exe' -File) {
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    $pe = [BitConverter]::ToInt32($bytes, 60)
    if ([Text.Encoding]::ASCII.GetString($bytes, $pe, 4) -ne "PE`0`0") { throw 'Invalid PE' }
    $optional = $pe + 24
    $directory = if ([BitConverter]::ToUInt16($bytes, $optional) -eq 0x20b) { $optional + 112 } else { $optional + 96 }
    $offset = [BitConverter]::ToInt32($bytes, $directory + 32)
    $length = [BitConverter]::ToInt32($bytes, $offset)
    $cms = [Security.Cryptography.Pkcs.SignedCms]::new()
    $cms.Decode([byte[]]$bytes[($offset + 8)..($offset + $length - 1)])
    $times = @()
    foreach ($signer in $cms.SignerInfos) {
        foreach ($counter in $signer.CounterSignerInfos) {
            foreach ($attr in $counter.SignedAttributes) {
                if ($attr.Oid.Value -eq '1.2.840.113549.1.9.5') {
                    foreach ($value in $attr.Values) { $times += ([Security.Cryptography.Pkcs.Pkcs9SigningTime]::new($value.RawData)).SigningTime.ToUniversalTime().ToString('o') }
                }
            }
        }
        foreach ($attr in $signer.UnsignedAttributes) {
            if ($attr.Oid.Value -eq '1.3.6.1.4.1.311.3.3.1') {
                foreach ($value in $attr.Values) {
                    $token = [Security.Cryptography.Pkcs.SignedCms]::new()
                    $token.Decode($value.RawData)
                    $content = [Text.Encoding]::ASCII.GetString($token.ContentInfo.Content)
                    foreach ($match in [regex]::Matches($content, '(?<!\d)(\d{14}(?:\.\d+)?Z)')) { $times += $match.Value }
                }
            }
        }
    }
    $sig = Get-AuthenticodeSignature -LiteralPath $file.FullName
    [ordered]@{name=$file.Name; size=$file.Length; sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLower(); version=$file.VersionInfo.FileVersion; signature_status=$sig.Status.ToString(); signer=$sig.SignerCertificate.Subject; timestamp_hints=@($times | Sort-Object -Unique)}
}
New-Item -ItemType Directory -Force -Path (Split-Path $Output) | Out-Null
ConvertTo-Json -InputObject @($rows) -Depth 8 | Set-Content -LiteralPath $Output -Encoding utf8
