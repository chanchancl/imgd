#!/usr/bin/env pwsh
# DataServer启动脚本 - PowerShell版本

param(
    [switch]$HideWindow = $false
)

# 如果未指定隐藏窗口，则隐藏窗口并重新运行
if (-not $HideWindow) {
    # 检查端口 8353 是否已被占用, 检测单例
    try {
        # 使用更可靠的端口检查方法
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $tcpClient.ReceiveTimeout = 500
        $tcpClient.SendTimeout = 500

        # 尝试连接，设置超时
        $asyncResult = $tcpClient.BeginConnect("127.0.0.1", 8353, $null, $null)

        # 等待连接完成或超时
        $waitHandle = $asyncResult.AsyncWaitHandle
        if ($waitHandle.WaitOne(500, $false)) {
            # 连接成功（端口被占用）
            $tcpClient.EndConnect($asyncResult)
            $tcpClient.Close()
            Write-Host "   Server already running on port 8353" -ForegroundColor Yellow
            Write-Host "   Another instance of dataserver is already running." -ForegroundColor Yellow
            Write-Host "   Exiting." -ForegroundColor Yellow
            Start-Sleep -Seconds 3
            exit 1
        } else {
            # 超时（端口可能可用，但更可能是连接被拒绝）
            $tcpClient.Close()
        }
    } catch {
        # 静默处理端口检查错误
    }


    # 隐藏窗口运行自身
    $psArgs = @('-WindowStyle', 'Hidden', '-File', $MyInvocation.MyCommand.Path, '-HideWindow')
    Start-Process powershell.exe -ArgumentList $psArgs -WindowStyle Hidden
    exit 0
}

# 运行 uvicorn
try {
    # 设置环境变量以启用托盘图标
    $env:DATASERVER_BAT = "1"
    uvicorn dataserver:app --host 127.0.0.1 --port 8353 --reload
} catch {
    exit 1
}