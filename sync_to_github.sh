#!/usr/bin/env bash
# 一键同步到 GitHub（自动探测已配置的 origin，无需手动填仓库地址）
set -e
cd "$(dirname "$0")"

echo "==> 探测远程仓库..."
ORIGIN=$(git remote get-url origin 2>/dev/null || true)
if [ -z "$ORIGIN" ]; then
  echo "未发现 origin，请先在 GitHub Desktop 添加本仓库，或手动："
  echo "  git remote add origin https://github.com/<你>/<仓库>.git"
  exit 1
fi
echo "    origin = $ORIGIN"

echo "==> 拉取最新..."
git pull origin "$(git branch --show-current)" --rebase || true

echo "==> 提交..."
git add -A
MSG="chore: 更新源池 + generate.py (UA/二次探测) [$(date +%Y-%m-%d_%H:%M)]"
git commit -m "$MSG" || echo "（无变更可提交）"

echo "==> 推送..."
git push -u origin "$(git branch --show-current)"
echo "==> 完成。稍后去 Actions 查看 Deploy 工作流运行结果。"
