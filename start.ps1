#!/usr/bin/env pwsh
# DataServer launch script
#   Double-click or direct run .\start.ps1   hidden window (silent)
#   .\start.ps1 -n                           no hide, run uvicorn in current shell

param(
    [switch]$n
)

# Without -n: hide window and run in background
if (-not $n) {
    # Check if port 8353 is already in use (singleton guard)
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $tcpClient.ReceiveTimeout = 100
        $tcpClient.SendTimeout = 100

        $asyncResult = $tcpClient.BeginConnect("127.0.0.1", 8353, $null, $null)
        $waitHandle = $asyncResult.AsyncWaitHandle

        if ($waitHandle.WaitOne(100, $false)) {
            $tcpClient.EndConnect($asyncResult)
            $tcpClient.Close()
            Write-Host "   Server already running on port 8353" -ForegroundColor Yellow
            Write-Host "   Another instance of dataserver is already running." -ForegroundColor Yellow
            Write-Host "   Exiting." -ForegroundColor Yellow
            Start-Sleep -Seconds 3
            exit 1
        } else {
            $tcpClient.Close()
        }
    } catch {
        # Silently ignore port check errors
    }

    Write-Host "Starting dataserver in background on port 8353..." -ForegroundColor Cyan

    # Re-launch with hidden window, child process uses -n to run directly
    $psArgs = @('-WindowStyle', 'Hidden', '-File', $MyInvocation.MyCommand.Path, '-n')
    Start-Process pwsh.exe -ArgumentList $psArgs -WindowStyle Hidden

    Start-Sleep -Seconds 3
    exit 0
}

# With -n: run uvicorn directly in the current shell
try {
    $env:TRAY_ICON = "true"
    uvicorn dataserver:app --host 127.0.0.1 --port 8353 --reload
} catch {
    exit 1
}
