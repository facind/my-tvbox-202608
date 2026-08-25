#!/bin/bash
# 一键生成：优先完整版（需 requests + pyyaml），否则 lite 版
set -e
cd "$(dirname "$0")"
python3 -c "import requests, yaml" 2>/dev/null && {
    echo "[使用完整版 generate.py]"
    python3 generate.py "$@"
} || {
    echo "[缺少依赖，使用 lite 版 generate_lite.py]"
    python3 generate_lite.py "$@"
}
