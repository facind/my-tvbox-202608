#!/bin/bash
# 影视仓聚合片源 - 一键发布到 GitHub（macOS / Linux）
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[*]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; exit 1; }

echo "==============================================================="
echo "  影视仓聚合片源 - 一键发布到 GitHub"
echo "==============================================================="
echo

# 1. 检查 git
command -v git >/dev/null || err "未检测到 git，请先安装：https://git-scm.com/downloads"

# 2. 交互收集参数
read -rp "【1/4】GitHub 仓库名 [默认 yingshicang]: " REPO_NAME
REPO_NAME=${REPO_NAME:-yingshicang}

read -rp "【2/4】你的 GitHub 用户名: " GITHUB_USER
[[ -z "$GITHUB_USER" ]] && err "用户名不能为空"

echo "【3/4】仓库可见性: 1) public(推荐)  2) private"
read -rp "请选择 [1/2，默认 1]: " VIS
[[ "$VIS" == "2" ]] && PRIVATE="--private" || PRIVATE="--public"

echo "【4/4】是否用 gh CLI 自动建仓+推送（需先 'gh auth login'）: 1) 是  2) 我已建好空仓库"
read -rp "请选择 [1/2，默认 1]: " MODE
MODE=${MODE:-1}

echo
echo "==============================================================="
echo "  仓库: $GITHUB_USER/$REPO_NAME  ($PRIVATE)"
echo "==============================================================="
echo

# 3. 初始化
[[ -d .git ]] || { info "初始化 git 仓库..."; git init -b main; git config user.name "$GITHUB_USER"; }
read -rp "git 邮箱（回车跳过）: " EMAIL
[[ -n "$EMAILIL" ]] || [[ -n "$EMAIL" ]] && git config user.email "$EMAIL"

# 4. 首次生成
info "生成聚合配置..."
if command -v python3 >/dev/null && [[ -f scripts/generate_lite.py ]]; then
    python3 scripts/generate_lite.py >/dev/null 2>&1 && info "已运行 generate_lite.py" \
        || warn "generate_lite.py 未运行（不影响发布，CI 会自动生成）"
fi

# 5. 提交
info "添加并提交..."
git add .
git status --short
git commit -m "chore: initial commit - 影视仓聚合片源 v1.0.0" || warn "无新变更可提交"

REMOTE="https://github.com/$GITHUB_USER/$REPO_NAME.git"

# 6. 推送
if [[ "$MODE" == "1" ]] && command -v gh >/dev/null; then
    info "使用 gh 创建仓库并推送..."
    gh repo create "$REPO_NAME" "$PRIVATE" \
        --source=. \
        --description "影视仓聚合片源 - 国内外影剧+百度/夸克/UC/阿里网盘，每3天自动更新" \
        --push && info "发布完成！" || {
        warn "gh 建仓失败，改用手动推送..."
        git remote remove origin >/dev/null 2>&1 || true
        git remote add origin "$REMOTE"
        git push -u origin main
    }
else
    git remote remove origin >/dev/null 2>&1 || true
    git remote add origin "$REMOTE"
    info "推送到 $REMOTE ..."
    git push -u origin main
fi

echo
echo "==============================================================="
echo "  发布完成！仓库: https://github.com/$GITHUB_USER/$REPO_NAME"
echo "==============================================================="
cat <<EOF

------------------------------------------------------------
 下一步（照着做）：

 [A] 设置自动更新密钥 (Settings → Secrets → Actions)
     ALIYUN_REFRESH_TOKEN = 你的阿里云盘 refresh_token
     （可选）BAIDU_COOKIE / QUARK_COOKIE / UC_COOKIE
     不设也能跑，网盘扫码兜底会用到。

 [B] 开启 GitHub Pages
     Settings → Pages → Source 选 "GitHub Actions"

 [C] 影视仓配置地址:
     https://$GITHUB_USER.github.io/$REPO_NAME/index.json

 [D] 自动更新已内置：每 3 天 06:00 UTC 自动生成+部署+提交
     （立即跑一次: Actions → Deploy → Run workflow）
------------------------------------------------------------
EOF
