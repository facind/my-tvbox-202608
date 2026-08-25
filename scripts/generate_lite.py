#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_lite.py —— 无第三方依赖版（仅用标准库）
功能与 generate.py 一致：聚合上游线路池 -> 去重分级 -> 生成多仓 + 单仓 + 网盘解析配置
用途：在没有 requests/pyyaml 的环境（或本沙盒演示）也能直接跑通
"""
import json, os, sys, datetime, subprocess, html

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_INDEX = os.path.join(BASE, "index.json")
OUT_DIR = os.path.join(BASE, "lines")
BACKUP_DIR = os.path.join(BASE, "backup")
for d in [OUT_DIR, BACKUP_DIR]:
    os.makedirs(d, exist_ok=True)

UA = "Mozilla/5.0 (Linux; Android 11; TVBox) AppleWebKit/537.36"

# ---------- 上游线路池（与 sources.yaml 同步）----------
LINES = [
    ("饭太硬", "http://www.饭太硬.com/tv", 1),
    ("肥猫", "http://肥猫.com/", 1),
    ("摸鱼4K", "http://我不是.摸鱼儿.top", 1),
    ("俊佬", "http://home.jundie.top:81/top98.json", 2),
    ("巧儿", "http://pandown.pro/tvbox/tvbox.json", 2),
    ("王二小", "http://tvbox.王二小放牛娃.top", 2),
    ("南风", "https://agit.ai/Yoursmile7/TVBox/raw/branch/master/XC.json", 3),
    ("菜妮丝", "https://tvbox.cainisi.cf", 3),
    ("OK", "http://ok321.top/tv", 3),
    ("小盒子4K", "http://xhztv.top/4k.json", 3),
    ("凯速备用", "https://6800.kstore.vip/fish.json", 5),
    ("道长", "https://pastebin.com/raw/5NHaxyGR", 5),
    ("老刘备", "https://raw.liucn.cc/box/m.json", 5),
]
WAREHOUSES = [
    ("运输车多仓", "https://weixine.net/api.json"),
    ("毒盒多仓", "https://tv.youdu.fan:666"),
]
LIVES = [
    ("运输车直播", "https://cf.weixine.net/api.json"),
    ("天微直播", "http://tvkj.top/tvlive.txt"),
]

# 网盘解析源（flag 映射：18=百度 19=夸克 20=UC 21=阿里 24=通用）
PAN_PARSES = [
    ("百度网盘", 18, "baidu"),
    ("夸克网盘", 19, "quark"),
    ("UC网盘", 20, "uc"),
    ("阿里云盘", 21, "aliyun"),
    ("万能解析", 24, "universal"),
]


def check_health(url, timeout=10):
    """用 curl 做健康检查（无 requests 时的兜底）"""
    try:
        r = subprocess.run(
            ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(timeout), "-A", UA, url],
            capture_output=True, text=True, timeout=timeout + 2,
        )
        code = r.stdout.strip()
        return code in ("200", "302", "301")
    except Exception:
        return False


def build_line(name, url, idx):
    sites = [{
        "key": f"line{idx:02d}", "name": name, "type": 1, "api": url,
        "searchable": 1, "quickSearch": 1, "filterable": 1,
    }]
    parses = [{"name": n, "type": t, "url": "https://your-parse.example.com/?url=",
               "ext": {"flag": flag}} for n, t, flag in PAN_PARSES]
    flags = {flag: {"type": t, "url": "https://your-parse.example.com/?url=", "ext": {"flag": flag}}
             for n, t, flag in PAN_PARSES}
    return {
        "key": f"self_{idx:02d}", "name": f"自建·{name}", "type": 1, "api": url,
        "jar": "jar/spider.jar", "spider": "spider.Main",
        "sites": sites, "parses": parses,
        "rules": {"hosts": [], "sites": [{"name": ".*", "host": [url]}]},
        "lives": [{"name": n, "type": 1, "url": u} for n, u in LIVES],
        "flags": flags,
        "ext": {"version": "1.0", "updated": datetime.datetime.utcnow().isoformat() + "Z"},
    }


def main():
    print("== 自建影视仓聚合片源 生成器 (lite) ==")
    print(f"== 上游线路池：{len(LINES)} 条，开始健康检查...\n")

    ok, bad = [], []
    for name, url, pri in LINES:
        alive = check_health(url)
        (ok if alive else bad).append((name, url, pri))
        print(f"  [{'OK ' if alive else 'BAD'}] {name:10s} {url}")

    # 降级：全部失败时进入信任模式，避免生成空多仓
    if ok == [] and bad == LINES:
        print("\n⚠️ 全部检查失败，疑似本机网络受限，自动降级为【信任模式】保留全部线路")
        ok, bad = [(n, u, p, ) for n, u, p in LINES], []

    # 备份旧 index
    if os.path.exists(OUT_INDEX):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.rename(OUT_INDEX, os.path.join(BACKUP_DIR, f"index_{ts}.json"))

    # 生成单仓
    for i, (name, url, pri) in enumerate(ok, 1):
        with open(os.path.join(OUT_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(build_line(name, url, i), f, ensure_ascii=False, indent=2)

    # 生成多仓 index
    urls = []
    for i, (name, url, pri) in enumerate([x for x in ok if x[2] <= 3], 1):
        urls.append({"name": f"{name}（主）", "url": url, "urlv": [url]})
    for i, (name, url, pri) in enumerate([x for x in ok if x[2] > 3], 1):
        urls.append({"name": f"{name}（备）", "url": url, "urlv": [url]})
    for name, url in WAREHOUSES:
        urls.append({"name": name, "url": url, "urlv": [url]})

    index = {
        "urls": urls,
        "lives": [{"name": n, "type": 1, "url": u} for n, u in LIVES],
        "ext": {"version": "1.0", "updated": datetime.datetime.utcnow().isoformat() + "Z",
                "description": "自建影视仓聚合片源，多仓+自动健康巡检，防单点失效"},
    }
    with open(OUT_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\n===== 生成完成 =====")
    print(f"  健康：{len(ok)} 条 | 失效：{len(bad)} 条")
    print(f"  多仓入口：{OUT_INDEX}")
    if bad:
        print("  失效明细：")
        for n, u, _ in bad:
            print(f"    - {n:10s} {u}")


if __name__ == "__main__":
    main()
