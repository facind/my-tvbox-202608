@echo off
chcp 65001 >nul
title 影视仓聚合源 - 一键发布到 GitHub
setlocal enabledelayedexpansion

echo ================================================================
echo   影视仓聚合片源 - 一键发布到 GitHub
echo   全程自动：初始化仓库 / 配置 / 首次生成 / 推送
echo ================================================================
echo.

REM ---------- 1. 检查 git ----------
where git >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 git，请先安装：https://git-scm.com/download/win
    echo        安装后重新打开此窗口再运行。
    pause
    exit /b 1
)

REM ---------- 2. 读取用户输入 ----------
set /p REPO_NAME=【1/4】输入 GitHub 仓库名（如 yingshicang，回车默认 yingshicang）: 
if "%REPO_NAME%"=="" set REPO_NAME=yingshicang

set /p GITHUB_USER=【2/4】输入你的 GitHub 用户名: 
if "%GITHUB_USER%"=="" (
    echo [错误] 用户名不能为空。
    pause
    exit /b 1
)

echo 【3/4】仓库可见性：
echo   1^) public  （推荐，GitHub Pages 免费 + 影视仓配置地址公网可访问）
echo   2^) private
set /p VIS=请选择 [1/2]（回车默认 1）: 
if "%VIS%"=="2" (set PRIVATE=--private) else (set PRIVATE=--public)

echo 【4/4】是否用 gh CLI 自动创建仓库 + 推送（推荐，需先 gh auth login）:
echo   1^) 是，自动创建并推送
echo   2^) 否，我已在 GitHub 网页建好空仓库，只推送
set /p MODE=请选择 [1/2]（回车默认 1）: 

echo.
echo ================================================================
echo   配置确认
echo   仓库: %GITHUB_USER%/%REPO_NAME%  (%PRIVATE%)
echo ================================================================
echo.

REM ---------- 3. 初始化 git ----------
if not exist ".git" (
    echo [1/5] 初始化 git 仓库...
    git init -b main
    git config user.name "%GITHUB_USER%"
    set /p EMAIL=输入 git 邮箱（回车跳过）: 
    if not "!EMAIL!"=="" git config user.email "!EMAIL!"
)

REM ---------- 4. 首次生成配置（确保 index.json 存在）----------
echo [2/5] 生成聚合配置...
where python >nul 2>nul
if not errorlevel 1 (
    if exist scripts\generate_lite.py (
        python scripts\generate_lite.py >nul 2>nul
        echo       已运行 generate_lite.py
    )
) else (
    echo       [提示] 未检测到 python，跳过生成；如需本地预览请安装 python。
)

REM ---------- 5. 添加并提交 ----------
echo [3/5] 添加文件并提交...
git add .
git status --short
git commit -m "chore: initial commit - 影视仓聚合片源 v1.0.0"

REM ---------- 6. 关联远程并推送 ----------
echo [4/5] 配置远程仓库...
git remote remove origin >nul 2>nul
set REMOTE=https://github.com/%GITHUB_USER%/%REPO_NAME%.git

if "%MODE%"=="2" goto :push_only

REM --- 模式1：用 gh 自动建仓并推送 ---
where gh >nul 2>nul
if errorlevel 1 (
    echo [提示] 未安装 GitHub CLI (gh)，跳过自动建仓。
    echo        请去 https://github.com/new 手动建空仓库 %REPO_NAME%，然后选模式2重跑。
    goto :manual
)
echo       使用 gh 创建仓库...
gh repo create %REPO_NAME% %PRIVATE% --source=. --description "影视仓聚合片源 - 国内外影剧+百度/夸克/UC/阿里网盘，每3天自动更新" --push
if errorlevel 1 (
    echo [提示] gh 建仓失败（可能仓库已存在），尝试仅添加远程并推送...
    git remote add origin %REMOTE%
    goto :push
)
echo.
echo ================================================================
echo   发布完成！
echo   仓库地址: https://github.com/%GITHUB_USER%/%REPO_NAME%
echo ================================================================
goto :next

:push_only
git remote add origin %REMOTE%
:manual
:push
echo [5/5] 推送到 GitHub...
git push -u origin main
if errorlevel 1 (
    echo.
    echo [错误] 推送失败。常见原因：
    echo   1. 仓库 %REPO_NAME% 在 GitHub 上还不存在 —— 去 https://github.com/new 建一个（不要勾选 README）
    echo   2. 未登录 —— 运行: git config ... 或安装 GitHub Desktop 登录
    echo   3. 首次认证失败 —— 用 GitHub Desktop 登录后重试最省事
    echo.
    echo 远程地址已配置为: %REMOTE%
    echo 解决后重新运行本脚本，或手动: git push -u origin main
    pause
    exit /b 1
)
echo.
echo ================================================================
echo   发布完成！
echo   仓库地址: https://github.com/%GITHUB_USER%/%REPO_NAME%
echo ================================================================

:next
echo.
echo ----------------------------------------------------------------
echo  下一步（重要，照着做）：
echo.
echo   [A] 设置自动更新所需的密钥（仓库 Settings → Secrets → Actions）
echo       Name: ALIYUN_REFRESH_TOKEN    Value: 你的阿里云盘 refresh_token
echo       （可选）BAIDU_COOKIE / QUARK_COOKIE / UC_COOKIE
echo       不设也能跑，但网盘扫码兜底会用到。
echo.
echo   [B] 开启 GitHub Pages
echo       Settings → Pages → Source 选 "GitHub Actions"
echo.
echo   [C] 影视仓配置地址（自动更新后的 index.json）:
echo       https://%GITHUB_USER%.github.io/%REPO_NAME%/index.json
echo.
echo   [D] 自动更新已内置：每 3 天 06:00 UTC 自动生成 + 部署 + 提交
echo       （如需立即跑一次: Actions → Deploy → Run workflow）
echo ----------------------------------------------------------------
echo.
pause
