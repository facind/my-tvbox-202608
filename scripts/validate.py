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
    # 1. index.json —— 兼容 旧格式{urls:[]} 和 新格式{sites:[]}
    idx_path = os.path.join(BASE, "index.json")
    check(os.path.exists(idx_path), "index.json 不存在")
    with open(idx_path, encoding="utf-8") as f:
        index = json.load(f)

    has_urls = isinstance(index.get("urls"), list) and index["urls"]
    has_sites = isinstance(index.get("sites"), list) and index["sites"]
    check(has_urls or has_sites, "index.json 既无 urls[] 也无 sites[]")

    if has_urls:
        for u in index["urls"]:
            check("name" in u and "url" in u, f"url 项缺少字段: {u}")
            check(u["url"].startswith("http"), f"url 非 http(s): {u['url']}")
        print(f"[OK] index.json(旧格式): {len(index['urls'])} 条线路入口, "
              f"{len(index.get('lives', []))} 个直播源")
    elif has_sites:
        for s in index["sites"]:
            check("name" in s and "api" in s, f"site 项缺少字段: {s}")
            api = s.get("api", "")
            # api 可以是 http(s) 链接，也可以是 csp_ 内置爬虫标识
            check(api.startswith("http") or api.startswith("csp_"),
                  f"api 非法(非 http 且非 csp_): {api}")
        print(f"[OK] index.json(新格式): {len(index['sites'])} 个站点, "
              f"{len(index.get('parses', []))} 个解析, {len(index.get('lives', []))} 个直播源")

    # 2. 每个单仓 line
    lines_dir = os.path.join(BASE, "lines")
    line_files = glob.glob(os.path.join(lines_dir, "*.json"))
    check(line_files, "lines/ 下没有生成单仓")
    for lf in line_files:
        with open(lf, encoding="utf-8") as f:
            data = json.load(f)
        name = os.path.basename(lf)

        # sites 必填，其余可选
        check(data.get("sites"), f"{name} 缺少 sites")
        if not data.get("parses"):
            warn.append(f"{name} 无 parses")
        if not data.get("lives"):
            warn.append(f"{name} 无 lives")

        # flags 可选：有就校验网盘齐全，没有就跳过
        flags = data.get("flags", {})
        if flags:
            for flag in ["baidu", "quark", "uc", "aliyun"]:
                check(flag in flags, f"{name} flags 缺少网盘: {flag}")
            # parses 里要有对应 type
            types = {p["type"] for p in data.get("parses", [])}
            for t, label in [(18, "百度"), (19, "夸克"), (20, "UC"), (21, "阿里")]:
                if t not in types:
                    warn.append(f"{name} parses 无 {label} 解析(type {t})")
        else:
            print(f"  ℹ️ {name} 无 flags（跳过网盘校验）")

        print(f"[OK] {name:14s} sites={len(data.get('sites', []))} "
              f"parses={len(data.get('parses', []))} lives={len(data.get('lives', []))}")

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
    print(f"✅ 全部校验通过（{len(line_files)} 个单仓）")


if __name__ == "__main__":
    main()