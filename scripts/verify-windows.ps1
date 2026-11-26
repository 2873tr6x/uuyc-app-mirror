param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Version)
$ErrorActionPreference = 'Stop'
$file = Get-Item -LiteralPath $Path
$signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
if ($signature.Status.ToString() -ne 'Valid') { throw "Invalid official Authenticode signature: $($signature.Status)" }
if (-not $signature.TimeStamperCertificate) { throw 'Official package lacks trusted timestamp signer' }
if ($signature.SignerCertificate.Subject -notmatch 'CN="?NetEase \(Hangzhou\) Network Co\., Ltd') { throw 'Unexpected publisher' }
if ($file.VersionInfo.FileVersion -ne $Version) { throw "Official internal version mismatch: $($file.VersionInfo.FileVersion)" }
[ordered]@{status=$signature.Status.ToString(); subject=$signature.SignerCertificate.Subject; certificate_thumbprint=$signature.SignerCertificate.Thumbprint; timestamp_subject=$signature.TimeStamperCertificate.Subject; file_version=$file.VersionInfo.FileVersion} | ConvertTo-Json -Compress
