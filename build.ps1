# ================================================================
#  Taskbar Todo 打包脚本 (PowerShell 版)
#  从 TaskbarTodo.spec 打包为单文件、无控制台的可执行程序。
#  （spec 内已处理 conda 多环境下 tcl/tk DLL 版本冲突问题）
# ================================================================

pyinstaller --noconfirm --clean TaskbarTodo.spec

if ($LASTEXITCODE -eq 0) {
    Write-Host "OK 打包完成！输出位于 dist/TaskbarTodo.exe" -ForegroundColor Green
} else {
    Write-Host "X 打包失败" -ForegroundColor Red
}
