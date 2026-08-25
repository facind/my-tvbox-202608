#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验生成的配置是否符合影视仓/TVBox 规范"""
import json, os, sys, glob

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
errors = []
warn = []


def check(cond, msg):
    if not cond:
        errors.append(msg)


def main():
    # 1. index.json
    idx_path = os.path.join(BASE, "index.json")
    check(os.path.exists(idx_path), "index.json 不存在")
    with open(idx_path, encoding="utf-8") as f:
        index = json.load(f)
    check(isinstance(index.get("urls"), list) and index["urls"], "index.json urls[] 为空或缺失")
    for u in index["urls"]:
        check("name" in u and "url" in u, f"url 项缺少字段: {u}")
        check(u["url"].startswith("http"), f"url 非 http(s): {u['url']}")
    print(f"[OK] index.json: {len(index['urls'])} 条线路入口, {len(index.get('lives', []))} 个直播源")

    # 2. 每个单仓 line
    lines_dir = os.path.join(BASE, "lines")
    line_files = glob.glob(os.path.join(lines_dir, "*.json"))
    check(line_files, "lines/ 下没有生成单仓")
    required = ["sites", "parses", "flags", "lives"]
    for lf in line_files:
        with open(lf, encoding="utf-8") as f:
            data = json.load(f)
        name = os.path.basename(lf)
        for key in required:
            check(key in data and data[key], f"{name} 缺少 {key}")
        # 网盘 flags 必须齐全
        for flag in ["baidu", "quark", "uc", "aliyun"]:
            check(flag in data.get("flags", {}), f"{name} flags 缺少网盘: {flag}")
        # parses 里要有对应 type
        types = {p["type"] for p in data["parses"]}
        for t, label in [(18, "百度"), (19, "夸克"), (20, "UC"), (21, "阿里")]:
            if t not in types:
                warn.append(f"{name} parses 无 {label} 解析(type {t})")
        print(f"[OK] {name:14s} sites={len(data['sites'])} parses={len(data['parses'])} lives={len(data['lives'])}")

    # 3. spider.jar 占位 + 源码
    jar = os.path.join(BASE, "jar", "spider.jar")
    java = os.path.join(BASE, "jar", "spider", "Main.java")
    check(os.path.exists(jar), "jar/spider.jar 缺失")
    check(os.path.exists(java), "spider 源码缺失")

    print()
    if warn:
        print("⚠️ 警告：")
        for w in warn:
            print(f"   - {w}")
    if errors:
        print("✖ 错误：")
        for e in errors:
            print(f"   - {e}")
        sys.exit(1)
    print(f"✅ 全部校验通过（{len(line_files)} 个单仓 + 1 个多仓）")


if __name__ == "__main__":
    main()
