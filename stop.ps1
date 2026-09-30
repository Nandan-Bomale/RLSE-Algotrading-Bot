$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' AND CommandLine LIKE '%main.py%'"
foreach ($p in $procs) {
    if ($p.ParentProcessId) {
        Stop-Process -Id $p.ParentProcessId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
