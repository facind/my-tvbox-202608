#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 ingest_public_sites / build_search_sites 逻辑正确性（离线 mock，不依赖网络）"""
import sys, os, json, importlib.util
sys.path.insert(0, os.path.dirname(__file__))

# 动态加载 generate.py（避免执行 __main__）
spec = importlib.util.spec_from_file_location("gen", os.path.join(os.path.dirname(__file__), "generate.py"))
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

results = []

def ok(cond, msg):
    results.append((bool(cond), msg))

# --- Mock _fetch_json：不联网，返回预设 JSON ---
fake = {
    "https://multi.com/api.json": {  # 多仓：含 urls[]
        "urls": [
            {"name": "子仓A", "url": "https://a.com/single.json"},
            {"name": "子仓B", "url": "https://b.com/single.json"},
        ]
    },
    "https://a.com/single.json": {  # 单仓：含 sites[]
        "sites": [
            {"key": "a1", "name": "站A1", "type": 1, "api": "https://api.a1", "searchable": 1},
            {"key": "a2", "name": "站A2", "type": 1, "api": "https://api.a2", "searchable": 0},  # 不可搜索，应被过滤
            {"name": "无key站", "type": 1, "api": "https://api.nokey", "searchable": 1},
        ]
    },
    "https://b.com/single.json": {
        "sites": [
            {"key": "b1", "name": "站B1", "type": 1, "api": "https://api.b1", "searchable": 1},
            {"key": "a1", "name": "重复站", "type": 1, "api": "https://api.a1", "searchable": 1},  # key 重复，应去重
        ]
    },
}
def mock_fetch(url, timeout=15):
    return fake.get(url)
gen._fetch_json = mock_fetch

ingest_cfg = {
    "enabled": True,
    "index_urls": ["https://multi.com/api.json"],
    "only_searchable": True,
    "prefer_stable": True,
    "max_sites_per_index": 30,
}
base_pool = [
    # 注意：不把 a.com/single.json 放进 base_pool，模拟"该仓来自公开索引、待吸收"
    {"key": "dup_key", "url": "https://other.com/x.json"},   # 用于验证 key 级去重
]

absorbed = gen.ingest_public_sites(ingest_cfg, base_pool, cap_per_index=30)
abs_keys = {s.get("key") for s in absorbed}

# 断言
ok("a1" in abs_keys, "a.com 仓被遍历，其可搜索站点 a1 应被吸收")
ok("a2" not in abs_keys, "searchable=0 的 a2 应被过滤")
ok(any(s.get("api") == "https://api.nokey" for s in absorbed), "无 key 的站以 api 作去重基准，应出现一次")
# 去重：让 b 仓里有个 key 与 base_pool 重复
fake["https://b.com/single.json"]["sites"].append(
    {"key": "dup_key", "name": "重复", "type": 1, "api": "https://dup", "searchable": 1}
)
absorbed2 = gen.ingest_public_sites(ingest_cfg, base_pool, cap_per_index=30)
abs_keys2 = {s.get("key") for s in absorbed2}
ok("dup_key" not in abs_keys2, "base_pool 已有的 key 应被去重，不再吸收")

# --- 测试 build_search_sites 规范化 ---
norm = gen.build_search_sites([
    {"key": "k1", "name": "S1", "type": 1, "api": "https://s1", "jar": "jar/x.jar", "spider": "spider.X"},
    {"api": "https://s2"},  # 缺 key/jar，应自动补
])
ok(len(norm) == 2, "规范化后数量保持 2")
ok(norm[0]["searchable"] == 1 and norm[0]["quickSearch"] == 1, "searchable/quickSearch 强制补 1")
ok(norm[1]["key"].startswith("search_"), "缺 key 自动生成 search_NN")
ok(norm[0]["jar"] == "jar/x.jar" and norm[0]["spider"] == "spider.X", "jar/spider 保留")

# --- 测试 disabled 时返回空 ---
empty = gen.ingest_public_sites({"enabled": False, "index_urls": ["x"]}, [], 30)
ok(empty == [], "enabled=false 时应返回空列表")

print("\n===== ingest / search_sites 单元测试 =====")
fail = 0
for passed, msg in results:
    print(f"  [{'OK' if passed else 'FAIL'}] {msg}")
    if not passed:
        fail += 1
print()
if fail:
    print(f"✖ {fail} 个测试失败")
    sys.exit(1)
print(f"✅ 全部 {len(results)} 个测试通过")
