# Safety-net stop for scripts/record_market_open.ps1, scheduled shortly
# after market close in case KIS keeps the session alive longer than
# expected. The recorder is expected to exit on its own once KIS closes
# the daily session (see src/api/kis_websocket.py) -- this is a backstop,
# not the primary shutdown path.

$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*src.main*--record*" }

foreach ($proc in $procs) {
    Stop-Process -Id $proc.ProcessId -Force
}
