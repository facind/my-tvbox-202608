#!/usr/bin/env bash
# ============================================================
#  一键把改动同步到你已存在的 GitHub 仓库（my-tvbox 或你改过的仓名）
#  用法：bash sync_to_github.sh
# ============================================================
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  把更新后的源同步到你的 GitHub 仓库"
echo "============================================================"

# 自动探测远程
REMOTE=$(git remote get-url origin 2>/dev/null || true)
if [ -z "$REMOTE" ]; then
  echo "⚠️ 未检测到 git 远程。请先确认你已在 GitHub Desktop 里 Add/Publish 过这个文件夹。"
  exit 1
fi
echo "[已探测到远程仓库] $REMOTE"

# 配置用户信息（仅本仓库）
git config user.email "facind@users.noreply.github.com" 2>/dev/null || true
git config user.name  "facind" 2>/dev/null || true

# 拉取最新
echo; echo "[1/4] 拉取远端最新..."
git pull origin main --no-rebase 2>/dev/null || git pull origin master --no-rebase 2>/dev/null || echo "（首次推送可忽略）"

# 暂存
echo; echo "[2/4] 暂存所有改动..."
git add .

# 提交
echo; echo "[3/4] 提交改动..."
if git commit -m "feat: 扩充 30+ 爬虫站 + 新增自动吸收公开单仓 sites（搜索结果增多 + 定期自增）"; then
  echo "提交完成。"
else
  echo "（没有新改动需要提交）"
fi

# 推送
echo; echo "[4/4] 推送到 GitHub..."
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push origin "$BRANCH" || {
  echo "⚠️ 推送失败。请先在 GitHub Desktop 点一次 Push 完成授权，或手动：git push -u origin $BRANCH"
  exit 1
}

echo
echo "============================================================"
echo "  ✅ 推送成功！"
echo "  你的 Actions 工作流会自动运行："
echo "    健康检查 → 吸收公开单仓 sites → 重新生成 index.json → 部署 Pages"
echo "  想立刻触发：仓库 → Actions → Deploy → Run workflow"
echo "  配置地址：https://facind.github.io/{仓名}/index.json"
echo "============================================================"
