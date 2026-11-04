<#
Authenticode-sign one file. Called by build/package.py for the exes and by Inno Setup
(SignTool) for the installer and uninstaller. Configure with environment variables:

  STUDIO_SIGN_THUMBPRINT   certificate in Cert:\CurrentUser\My or Cert:\LocalMachine\My
                           (works for hardware-token / EV certificates installed there)
  STUDIO_SIGN_PFX          path to a .pfx file, with STUDIO_SIGN_PFX_PASSWORD
  STUDIO_SIGN_COMMAND      any other signer (Azure Trusted Signing, SignPath, a signtool
                           invocation...); "{file}" is replaced with the path to sign
  STUDIO_SIGN_TIMESTAMP    RFC 3161 timestamp server (default http://timestamp.digicert.com)
#>
param([Parameter(Mandatory = $true)][string]$Path)
$ErrorActionPreference = "Stop"

if ($env:STUDIO_SIGN_COMMAND) {
    $cmd = $env:STUDIO_SIGN_COMMAND.Replace("{file}", "`"$Path`"")
    cmd.exe /c $cmd
    if ($LASTEXITCODE -ne 0) { throw "signing command failed ($LASTEXITCODE)" }
    exit 0
}

if ($env:STUDIO_SIGN_PFX) {
    $flags = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
        $env:STUDIO_SIGN_PFX, $env:STUDIO_SIGN_PFX_PASSWORD, $flags)
} elseif ($env:STUDIO_SIGN_THUMBPRINT) {
    $thumb = $env:STUDIO_SIGN_THUMBPRINT.Replace(" ", "").ToUpper()
    $cert = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My -CodeSigningCert |
        Where-Object { $_.Thumbprint -eq $thumb } | Select-Object -First 1
    if (-not $cert) { throw "no code-signing certificate with thumbprint $thumb in CurrentUser\My or LocalMachine\My" }
} else {
    throw "set STUDIO_SIGN_THUMBPRINT, STUDIO_SIGN_PFX or STUDIO_SIGN_COMMAND"
}

$ts = if ($env:STUDIO_SIGN_TIMESTAMP) { $env:STUDIO_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
$result = $null
for ($attempt = 1; $attempt -le 3 -and -not $result.SignerCertificate; $attempt++) {
    try {
        $result = Set-AuthenticodeSignature -LiteralPath $Path -Certificate $cert -TimestampServer $ts -HashAlgorithm SHA256
    } catch {
        if ($attempt -eq 3) { throw }
        Start-Sleep -Seconds (2 * $attempt)  # timestamp servers are occasionally flaky
    }
}
if (-not $result.SignerCertificate -or $result.Status -eq "HashMismatch" -or $result.Status -eq "NotSigned") {
    throw "signing $Path failed: $($result.Status) $($result.StatusMessage)"
}
# "UnknownError" here means signed with a certificate this PC doesn't trust (e.g. a test cert).
Write-Host "signed $(Split-Path $Path -Leaf): $($result.Status)"
