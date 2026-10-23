# Builds Linphone Dialer, installs it for this Windows user (replacing any earlier copy) and
# opens it once, which points Linphone's phone links at it.
#   powershell -ExecutionPolicy Bypass -File build.ps1 [destination folder]
#   (default: %LOCALAPPDATA%\Programs\Linphone Dialer)
# Needs nothing beyond Windows itself: the C# compiler and UI Automation come with .NET
# Framework 4.
param([string]$Dest = "$env:LOCALAPPDATA\Programs\Linphone Dialer")
$ErrorActionPreference = 'Stop'

$fw = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319"
$work = Join-Path ([IO.Path]::GetTempPath()) "linphone-dialer-$([guid]::NewGuid())"
New-Item -ItemType Directory $work | Out-Null
try {
    & "$fw\csc.exe" /nologo /target:winexe /optimize+ /out:"$work\LinphoneDialer.exe" `
        /r:"$fw\WPF\UIAutomationClient.dll" /r:"$fw\WPF\UIAutomationTypes.dll" /r:"$fw\WPF\WindowsBase.dll" `
        /r:System.Windows.Forms.dll "$PSScriptRoot\LinphoneDialer.cs"
    if ($LASTEXITCODE) { throw "the C# compiler failed, see above" }
    New-Item -ItemType Directory -Force $Dest | Out-Null
    Move-Item -Force "$work\LinphoneDialer.exe" "$Dest\LinphoneDialer.exe"
} finally {
    Remove-Item -Recurse -Force $work
}
"Installed $Dest\LinphoneDialer.exe."
& "$Dest\LinphoneDialer.exe"
