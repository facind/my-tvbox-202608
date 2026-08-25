#!/usr/bin/env python3
"""
本地模拟发布验证：
1. 模拟 git add . 后的暂存文件清单（尊重 .gitignore）
2. 校验关键目录结构完整（scripts/lines/jar/.github/workflows/ 都在）
3. 校验发布脚本、教程、README 存在
4. 打印最终推送到 GitHub 的结构树
"""
import os
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
GITIGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8")

# 解析 .gitignore 规则（简化：只处理纯文件名/目录名/通配）
ignore_patterns = []
for line in GITIGNORE.splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    ignore_patterns.append(line)

def ignored(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    for pat in ignore_patterns:
        # 目录规则
        if pat.endswith("/"):
            d = pat.rstrip("/")
            if d in parts:
                return True
        # 通配
        if "*" in pat:
            regex = re.escape(pat).replace(r"\*", ".*")
            if re.search(regex, path.replace("\\", "/")):
                return True
        # 精确/后缀
        if pat in parts or any(p == pat for p in parts):
            return True
        if path.endswith(pat.lstrip("*").lstrip(".").replace("*", "")) and pat.startswith("*"):
            return True
    return False

all_files = []
for dirpath, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if not d.startswith(".") or d in (".github",)]
    for f in files:
        full = Path(dirpath) / f
        rel = full.relative_to(ROOT).as_posix()
        if ignored(rel):
            continue
        all_files.append(rel)

all_files.sort()

required = [
    "README.md", "发布教程.md", "publish.bat", "publish.sh", ".gitignore",
    ".github/workflows/deploy.yml",
    "index.json", "sources.yaml", "config.env",
    "scripts/generate.py", "scripts/generate_lite.py", "scripts/validate.py", "scripts/run.sh",
    "jar/spider/Main.java", "jar/spider/Spider.java",
    "jar/spider/js/spider.js",
    "jar/spider/js/pan_aliyun.js", "jar/spider/js/pan_baidu.js", "jar/spider/js/pan_quark_uc.js",
    "jar/build.sh", "jar/test_spider.js",
    "lines/.gitkeep", "backup/.gitkeep",
]
missing = [r for r in required if r not in all_files]

print("=" * 60)
print("待上传文件清单（模拟 git add . 后，已应用 .gitignore）")
print("=" * 60)
for f in all_files:
    print(f"  {f}")
print("-" * 60)
print(f"共 {len(all_files)} 个文件将被推送到 GitHub")
print()

# 目录树
tree = {}
for f in all_files:
    cur = tree
    for seg in f.split("/"):
        cur = cur.setdefault(seg, {})

def render(node, prefix=""):
    keys = sorted(node.keys())
    for i, k in enumerate(keys):
        last = i == len(keys) - 1
        print(f"{prefix}{'└── ' if last else '├── '}{k}{'/' if node[k] else ''}")
        if node[k]:
            render(node[k], prefix + ("    " if last else "│   "))

print("GitHub 仓库结构树：")
render(tree)
print()

if missing:
    print("❌ 缺少关键文件：")
    for m in missing:
        print(f"   - {m}")
    raise SystemExit(1)
print("✅ 所有关键目录/文件齐全，可直接发布")
