@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==^> 探测远程仓库...
for /f "tokens=*" %%a in ('git remote get-url origin 2^>nul') do set ORIGIN=%%a
if "%ORIGIN%"=="" (
  echo 未发现 origin，请先在 GitHub Desktop 添加本仓库。
  pause & exit /b 1
)
echo    origin = %ORIGIN%
echo ==^> 拉取最新...
git pull origin %BRANCH% --rebase 2>nul || true
echo ==^> 提交...
git add -A
git commit -m "chore: 更新源池 + generate.py (UA/二次探测) [%date%_%time%]" || echo （无变更）
echo ==^> 推送...
git push -u origin %BRANCH%
echo ==^> 完成。去 Actions 查看 Deploy。
pause
