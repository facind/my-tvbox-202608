#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地单元测试：不依赖网络，验证 generate.py 的三档逻辑 / 去重 / 二次探测。
跑法：python3 scripts/test_generate.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generate as G

OK = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
count = [0, 0]

def check(name, cond):
    count[0] += 1
    if cond:
        count[1] += 1
        print(f"  {OK} {name}")
    else:
        print(f"  {FAIL} {name}")
    return cond


def make_resp(status, text):
    class R:
        def __init__(s, st, t):
            s.status_code = st
            s.text = t
            s.content = t.encode("utf-8", "ignore")
        def json(s):
            import json as j
            return j.loads(s.text)
    return R(status, text)


print("\n[1] _is_dead_page 售卖/错误页识别")
check("域名售卖页识别", G._is_dead_page("xxx 域名售卖 page") == "域名售卖")
check("afternic 识别", G._is_dead_page("Domain is for sale Afternic") == "afternic")
check("正常页返回 None", G._is_dead_page("正常的影视列表页面内容") is None)

print("\n[2] _looks_like_tvbox_json 单仓结构识别")
check("含 sites -> True", G._looks_like_tvbox_json({"sites": [{"key": "a"}]}))
check("含 spider -> True", G._looks_like_tvbox_json({"spider": "csp_X"}))
check("含 class -> True", G._looks_like_tvbox_json({"class": []}))
check("空 dict -> False", not G._looks_like_tvbox_json({}))
check("纯对象无特征 -> False", not G._looks_like_tvbox_json({"name": "x"}))
check("非空 list -> True", G._looks_like_tvbox_json([{"a": 1}]))
check("空 list -> False", not G._looks_like_tvbox_json([]))

print("\n[3] check_one 三档判定（monkeypatch _fetch_with_retry）")
call_count = {}
def fake_fetch(url, headers=None):
    is_player = bool(headers and "player" in str(headers.get("User-Agent", "")))
    call_count.setdefault(url, 0)
    call_count[url] += 1
    n = call_count[url]
    if "dead" in url:
        return None, "timeout"
    if "sale" in url:
        return make_resp(200, "<html>域名售卖 afternic</html>"), ""
    if "upgrade" in url:
        # 首次(普通UA)返回 HTML，二次(player UA)返回 JSON -> 应升级为 VALID
        if n >= 2:
            return make_resp(200, '{"sites": [{"key": "k"}]}'), ""
        return make_resp(200, "<html>导航页 " + "y" * 300 + "</html>"), ""
    if "nav" in url:
        return make_resp(200, "<html>导航页正常内容 " + "x" * 300 + "</html>"), ""
    if "valid" in url:
        return make_resp(200, '{"sites": [{"key": "a"}, {"key": "b"}]}'), ""
    return make_resp(200, "short"), ""
G._fetch_with_retry = fake_fetch

res = G.check_one({"name": "v", "url": "http://valid"})
check("标准 JSON -> VALID", res["_status"] == "valid")
res = G.check_one({"name": "s", "url": "http://dead"})
check("超时/拒绝 -> DEAD", res["_status"] == "dead")
res = G.check_one({"name": "s", "url": "http://sale"})
check("售卖页 -> DEAD", res["_status"] == "dead")
res = G.check_one({"name": "n", "url": "http://nav"})
check("HTML 导航页(无升级) -> NAV", res["_status"] == "nav")
res = G.check_one({"name": "u", "url": "http://upgrade"})
check("二次探测拿到 JSON -> 升级为 VALID", res["_status"] == "valid")

print("\n[4] build_index / write_lines / 去重")
valid = [{"name": "A", "url": "u1", "priority": 1}, {"name": "B", "url": "u2", "priority": 2}]
nav = [{"name": "C", "url": "u3", "priority": 5}]
wh = [{"name": "多仓X", "url": "https://wx.json"}]
idx = G.build_index(valid, nav, wh, [{"name": "直播1", "url": "https://live"}])
check("入口 = valid+nav+多仓", len(idx["urls"]) == 4)
check("priority<=3 标主", any("（主）" in u["name"] for u in idx["urls"]))
check("priority>3 标备", any("（备）" in u["name"] for u in idx["urls"]))
check("多仓进入口", any(u["name"] == "多仓X" for u in idx["urls"]))
check("lives 写入", idx["lives"][0]["name"] == "直播1")

# write_lines 生成单仓含并联搜索站
written = G.write_lines(valid, [{"name": "直播1", "url": "https://live"}],
                        [{"key": "s1", "name": "S1", "type": 1, "api": "https://s1", "searchable": 1}])
check("生成单仓文件数=2", len(written) == 2)
line0 = json.load(open(os.path.join(G.BASE, written[0][0]), encoding="utf-8"))
check("单仓 sites 含主站+搜索站", len(line0["sites"]) == 2)

print("\n[5] build_search_sites 规范化 + 去重 key")
pool = [
    {"key": "a", "name": "A", "api": "https://a", "searchable": 1},
    {"key": "a", "name": "A2", "api": "https://a2", "searchable": 1},  # 重复 key 应被吸收去重
    {"key": "b", "name": "B", "api": "https://b", "searchable": 1, "jar": "jar/spider.jar", "spider": "spider.Main"},
]
norm = G.build_search_sites(pool)
check("去重后=2条", len(norm) == 2)
check("带 jar 保留字段", any(s.get("jar") for s in norm))
check("默认 searchable=1", all(s["searchable"] == 1 for s in norm))

print("\n[6] skip_check 强制保留")
res = G.check_one({"name": "force", "url": "http://dead", "skip_check": True})
check("skip_check -> VALID", res["_status"] == "valid")

print(f"\n===== 结果: {count[1]}/{count[0]} 通过 =====")
sys.exit(0 if count[0] == count[1] else 1)
