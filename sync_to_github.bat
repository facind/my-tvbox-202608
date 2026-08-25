@echo off
chcp 65001 >nul
REM ============================================================
REM  一键把改动同步到你已存在的 GitHub 仓库（my-tvbox 或你改过的仓名）
REM  用法：双击运行，或在仓库根目录执行 sync_to_github.bat
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   把更新后的源同步到你的 GitHub 仓库
echo ============================================================
echo.

REM --- 自动探测当前 git 仓库的远程地址 ---
for /f "tokens=*" %%a in ('git remote get-url origin 2^>nul') do set "REMOTE=%%a"
if defined REMOTE (
  echo [已探测到远程仓库] !REMOTE!
) else (
  echo [未检测到 git 远程] 请先确认你在 GitHub Desktop 里已经 "Add Local Repository" 了这个文件夹。
  echo 如果你是从 zip 解压的全新文件夹，请先在 GitHub Desktop 里 Publish 一次（参考发布教程.md）。
  pause
  exit /b 1
)
echo.

REM --- 配置 git 用户信息（仅本仓库，不影响全局）---
git config user.email "facind@users.noreply.github.com" 2>nul
git config user.name  "facind" 2>nul

REM --- 拉取远端最新（避免冲突）---
echo [1/4] 拉取远端最新提交...
git pull origin main --no-rebase 2>nul || git pull origin master --no-rebase 2>nul || echo （首次推送可忽略）

REM --- 添加所有改动 ---
echo.
echo [2/4] 暂存所有改动...
git add .

REM --- 提交 ---
echo.
echo [3/4] 提交改动...
set "MSG=feat: 扩充 30+ 爬虫站 + 新增自动吸收公开单仓 sites（搜索结果增多 + 定期自增）"
git commit -m "%MSG%" 2>&1 | findstr /c:"nothing to commit" >nul && (
  echo （没有新改动需要提交）
) || (
  echo 提交完成。
)

REM --- 推送 ---
echo.
echo [4/4] 推送到 GitHub...
git push origin main 2>nul || git push origin master 2>nul
if !errorlevel! neq 0 (
  echo.
  echo ⚠️ 推送失败。常见原因与解决办法：
  echo   1) 需要登录授权：打开 GitHub Desktop，点一次 "Push" 让它弹出登录窗口。
  echo   2) 首次推送需设上游：手动执行  git push -u origin main
  echo   3) 远程仓库是空仓：先在网页删除旧仓，再用 GitHub Desktop 重新 Publish。
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   ✅ 推送成功！
echo   你的 Actions 工作流会在几分钟内自动运行：
echo     健康检查 → 吸收公开单仓 sites → 重新生成 index.json → 部署 Pages
echo   想立刻触发：仓库 → Actions → Deploy → Run workflow
echo   最终配置地址：https://facind.github.io/{仓名}/index.json
echo ============================================================
pause
endlocal
