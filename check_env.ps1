# check_env.ps1 —— 演示前跑一次，确认环境是干净的
#
#     .\check_env.ps1
#
# 检查四件事：
#   ① 端口 8000 上有没有残留的服务进程   ← 最容易被忽略，也最坑
#   ② 有没有多余的 python 进程（旧实例 / MCP 孤儿进程）
#   ③ 集群里的 Pod 状态
#   ④ Redis / Qdrant 通不通
#
# 为什么值得单独写一个脚本：
#   "端口被占"造成的症状是「演示卡住」或者「改了代码却没生效」，
#   而真正的原因在【另一个进程】里 —— 很容易顺着错方向查很久。

Write-Host ""
Write-Host "=== ① 端口 8000 ===" -ForegroundColor Cyan
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $conn | ForEach-Object {
        $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        Write-Host ("  !! 被占用：PID {0} {1}，启动于 {2}" -f $p.Id, $p.ProcessName, $p.StartTime) -ForegroundColor Red
        Write-Host ("     → 确认是本项目的进程后：Stop-Process -Id {0} -Force" -f $p.Id) -ForegroundColor Yellow
    }
} else {
    Write-Host "  OK  空闲" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== ② python 进程（正常只有 1 个：服务主进程）===" -ForegroundColor Cyan
$pys = @(Get-Process python -ErrorAction SilentlyContinue)
if ($pys.Count -eq 0) {
    Write-Host "  （没有 python 在跑）" -ForegroundColor Green
} else {
    $pys | Select-Object Id, StartTime | Sort-Object StartTime | Format-Table -AutoSize | Out-String | Write-Host
    if ($pys.Count -gt 1) {
        Write-Host "  !! 多于 1 个：可能有旧实例，或者被强杀后留下的 MCP 子进程" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== ③ 集群 ===" -ForegroundColor Cyan
kubectl -n prod-order get pods

Write-Host ""
Write-Host "=== ④ 依赖 ===" -ForegroundColor Cyan
foreach ($svc in @(@{n = "Redis "; p = 6379 }, @{n = "Qdrant"; p = 6343 })) {
    $ok = Test-NetConnection 127.0.0.1 -Port $svc.p -InformationLevel Quiet -WarningAction SilentlyContinue
    if ($ok) { Write-Host ("  OK  {0} {1}" -f $svc.n, $svc.p) -ForegroundColor Green }
    else { Write-Host ("  !!  {0} {1} 不通 —— docker compose up -d" -f $svc.n, $svc.p) -ForegroundColor Red }
}

Write-Host ""
