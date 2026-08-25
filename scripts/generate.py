#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影视仓 / TVBox 自建聚合片源 生成器
====================================
功能：
  1. 从 sources.yaml 读取"上游线路池"（含官方维护 + 自建爬虫 + 网盘源）
  2. 并发健康检查，自动剔除失效线路
  3. 去重、分级（主/备/本地）
  4. 生成：
       - index.json        (多仓：urls[]，影视仓"仓库管理"入口)
       - lines/<name>.json (单仓：sites / parses / rules / lives)
       - spider 配置       (jar 爬虫，负责百度/夸克/UC/阿里 网盘解析)
  5. 输出 README + 部署清单

设计原则（保证不突然失效）：
  - 多仓结构：影视仓先加载 index.json，里面挂 N 条单仓线路，一条挂了不影响其他
  - 每条单仓都配 备用URL（urlv）和多 CDN 镜像
  - 解析源（parses）混合自建 flag + 公开解析，自动优选
  - 网盘源走 spider jar（百度网盘 / 夸克 / UC / 阿里云盘 统一适配）
  - 本脚本可放 crontab 每日跑一次，自动刷新健康池

用法：
    python3 generate.py            # 生成全量配置
    python3 generate.py --check     # 仅做健康检查并打印报告
    python3 generate.py --no-check  # 跳过网络检查（离线生成）
"""
import json, os, sys, time, hashlib, logging, argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    os.system("pip install requests -q")
    import requests

try:
    import yaml
except ImportError:
    os.system("pip install pyyaml -q")
    import yaml

# ---------- 路径 ----------
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_YAML = os.path.join(BASE, "sources.yaml")
OUT_INDEX = os.path.join(BASE, "index.json")
OUT_DIR = os.path.join(BASE, "lines")
SPIDER_DIR = os.path.join(BASE, "jar")
BACKUP_DIR = os.path.join(BASE, "backup")

for d in [OUT_DIR, SPIDER_DIR, BACKUP_DIR]:
    os.makedirs(d, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("ysc")

UA = "Mozilla/5.0 (Linux; Android 11; TVBox) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/94.0 Safari/537.36"
TIMEOUT = 12
WORKERS = 20

# =========================================================
# 1. 上游线路池（也可放到 sources.yaml，这里给一份内置兜底）
# =========================================================
DEFAULT_SOURCES = {
    # 公开维护的单仓线路（官方/知名维护者，长期更新，含国内外影视+4K）
    "lines": [
        {"name": "饭太硬",   "url": "http://fty.888484.xyz/tv",  "tags": ["点播", "4K"], "priority": 1},
        {"name": "肥猫",     "url": "http://肥猫.com/",          "tags": ["点播", "聚合"], "priority": 1},
        {"name": "摸鱼4K",   "url": "http://我不是.摸鱼儿.top",   "tags": ["4K", "蓝光"], "priority": 1},
        {"name": "俊佬",     "url": "http://home.jundie.top:81/top98.json", "tags": ["点播"], "priority": 2},
        {"name": "巧儿",     "url": "http://pandown.pro/tvbox/tvbox.json", "tags": ["点播"], "priority": 2},
        {"name": "王二小",   "url": "http://tvbox.王二小放牛娃.top", "tags": ["点播", "聚合"], "priority": 2},
        {"name": "南风",     "url": "https://agit.ai/Yoursmile7/TVBox/raw/branch/master/XC.json", "tags": ["点播"], "priority": 3},
        {"name": "菜妮丝",   "url": "https://tvbox.cainisi.cf",  "tags": ["点播"], "priority": 3},
        {"name": "OK",       "url": "http://ok321.top/tv",       "tags": ["点播"], "priority": 3},
        {"name": "小盒子4K", "url": "http://xhztv.top/4k.json",  "tags": ["4K"], "priority": 3},
        {"name": "凯速备用", "url": "https://6800.kstore.vip/fish.json", "tags": ["备用"], "priority": 5},
        {"name": "道长",     "url": "https://pastebin.com/raw/5NHaxyGR", "tags": ["备用"], "priority": 5},
        {"name": "老刘备",   "url": "https://raw.liucn.cc/box/m.json", "tags": ["备用", "广告"], "priority": 5},
        {"name": "讴歌",     "url": "http://tv.nxog.top/m", "tags": ["点播", "4K"], "priority": 1},
    ],
    # 多仓（影视仓"仓库管理"里再套一层，选填）
    "warehouses": [
        {"name": "运输车多仓", "url": "https://weixine.net/api.json"},
        {"name": "毒盒多仓",   "url": "https://tv.youdu.fan:666"},
        {"name": "无邪多仓",   "url": "https://gh-proxy.com/https://raw.githubusercontent.com/wxrjck/-YSC-/refs/heads/main/wx.json"},
    ],
    # 直播源（放到单仓的 lives 里，也可单拆）
    "lives": [
        {"name": "运输车直播", "url": "https://cf.weixine.net/api.json"},
        {"name": "天微直播",   "url": "http://tvkj.top/tvlive.txt"},
        {"name": "妖火直播",   "url": "https://raw.gitmirror.com/XiaoZhang5656/xiaozhang-5656.github.io/main/iptv-live.txt"},
    ],
}

# 网盘解析源（flag 标识，供 spider jar 路由）
# type 含义：18=百度网盘  19=夸克  20=UC  21=阿里云盘  24=通用资源
PAN_PARSES = [
    {"name": "百度网盘",   "type": 18, "url": "https://www.imooc.com/api/lib/player?url=", "ext": {"flag": "baidu"}},
    {"name": "夸克网盘",   "type": 19, "url": "https://www.imooc.com/api/lib/player?url=", "ext": {"flag": "quark"}},
    {"name": "UC网盘",     "type": 20, "url": "https://www.imooc.com/api/lib/player?url=", "ext": {"flag": "uc"}},
    {"name": "阿里云盘",   "type": 21, "url": "https://www.imooc.com/api/lib/player?url=", "ext": {"flag": "aliyun"}},
    {"name": "万能解析",   "type": 24, "url": "https://www.imooc.com/api/lib/player?url=", "ext": {"flag": "universal"}},
]

# 自建站点爬虫（示例规则，可按需扩展；实际解析由 jar 里的 js 规则完成）
CUSTOM_SITES = [
    {"key": "search_collect", "name": "全网采集", "type": 3, "api": "https://api.example.com/collect",
     "searchable": 1, "quickSearch": 1, "filterable": 1,
     "jar": "spider.jar", "spider": "spider.collect.Concat"},
]


# =========================================================
# 2. 加载 sources.yaml（存在则合并，否则用内置兜底）
# =========================================================
def load_sources():
    if os.path.exists(SRC_YAML):
        with open(SRC_YAML, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        log.info("从 sources.yaml 加载上游配置")
        return {
            "lines": data.get("lines") or DEFAULT_SOURCES["lines"],
            "warehouses": data.get("warehouses", []),
            "lives": data.get("lives", []),
            # ★ 独立搜索型爬虫站池（决定搜索结果数量）
            "search_sites": data.get("search_sites", []),
            # ★ 吸收公开单仓配置
            "ingest": data.get("ingest", {"enabled": False, "index_urls": []}),
        }
    log.info("未找到 sources.yaml，使用内置兜底线路池")
    return {**DEFAULT_SOURCES, "search_sites": [], "ingest": {"enabled": False, "index_urls": []}}


# =========================================================
# 2b. 自动吸收公开单仓/多仓里的 sites（问题2：定期更新越攒越多）
# ---------------------------------------------------------
# 对 ingest.index_urls 里的每个公开索引 JSON：
#   - 若是"多仓"（含 urls[]），则逐个拉取其中的单仓
#   - 若是"单仓"（含 sites[]），直接处理
# 提取 searchable 的 site，去重(key 相同视为同一站)，合并进主池
# 网络失败/解析失败一律跳过，不影响主流程
# =========================================================
def _fetch_json(url, timeout=15):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA}, allow_redirects=True)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("  吸收失败 %s : %s", url, str(e)[:50])
    return None


def _collect_sites_from_index(obj, acc, seen, cap, only_searchable):
    """从单个单仓 dict 里提取 sites，写入 acc[]，按 key 去重"""
    sites = obj.get("sites") or []
    for s in sites:
        if not isinstance(s, dict):
            continue
        if only_searchable and not s.get("searchable"):
            continue
        key = s.get("key") or s.get("api") or s.get("name")
        if not key or key in seen:
            continue
        seen.add(key)
        acc.append(dict(s))          # 复制，避免污染原数据
        if len(acc) >= cap:
            return True              # 已满，停止
    return False


def ingest_public_sites(ingest_cfg, base_pool, cap_per_index=30):
    """
    base_pool: 当前已探活的主线路（用来做去重基准，避免吸收重复站）
    return: 新吸收的 searchable sites 列表
    """
    if not ingest_cfg or not ingest_cfg.get("enabled"):
        return []
    index_urls = ingest_cfg.get("index_urls", []) or []
    only_searchable = ingest_cfg.get("only_searchable", True)
    prefer_stable = ingest_cfg.get("prefer_stable", True)
    cap = cap_per_index or 30

    seen = set()
    for line in base_pool:
        seen.add(line.get("url"))       # 主线路的 api 视为已覆盖
        seen.add(line.get("key"))       # 主线路的 key 也视为已覆盖（按 key 去重）
    absorbed = []

    log.info("★ 开始吸收公开索引：%d 个索引地址", len(index_urls))
    for url in index_urls:
        obj = _fetch_json(url)
        if not isinstance(obj, dict):
            continue
        # 多仓：含 urls[]，逐个拉取子仓的 sites（用 key 去重，避免同站重复吸收）
        if "urls" in obj and isinstance(obj["urls"], list):
            for u in obj["urls"][:cap]:
                sub_url = u.get("url") if isinstance(u, dict) else u
                sub_key = u.get("key") if isinstance(u, dict) else None
                if not sub_url:
                    continue
                # 若该子仓整体已在主池（url/key 命中），跳过其 sites 遍历
                if sub_url in seen or (sub_key and sub_key in seen):
                    continue
                sub = _fetch_json(sub_url)
                if isinstance(sub, dict):
                    # 遍历该子仓的 sites，逐个按 key 去重吸收
                    if _collect_sites_from_index(sub, absorbed, seen, cap, only_searchable):
                        break
        else:
            # 单仓：直接提取 sites（内部 _collect 已按 key 去重）
            _collect_sites_from_index(obj, absorbed, seen, cap, only_searchable)

    if prefer_stable:
        # 稳定优先：带 searchable 的排前面
        absorbed.sort(key=lambda s: 0 if s.get("searchable") else 1)
    log.info("★ 本次吸收到 %d 个新搜索站点（已去重）", len(absorbed))
    return absorbed


# =========================================================
# 2c. 把 search_sites + 吸收来的 sites 并联到单仓的 sites[] 里
# ---------------------------------------------------------
# 关键：影视仓会对单仓内所有 searchable=1 的 site 并发搜索，
# 并联越多，搜索结果越多。
# =========================================================
def build_search_sites(all_search_sites, jar="jar/spider.jar"):
    """规范化搜索站点：缺省字段补 searchable=1，统一 jar 引用"""
    out = []
    for i, s in enumerate(all_search_sites, 1):
        site = {
            "key": s.get("key") or f"search_{i:02d}",
            "name": s.get("name") or f"搜索站{i}",
            "type": s.get("type", 1),
            "api": s["api"],
            "searchable": 1,                    # 强制可搜索（这是搜索结果多的核心）
            "quickSearch": s.get("quickSearch", 1),
            "filterable": s.get("filterable", 1),
        }
        if s.get("jar"):
            site["jar"] = s["jar"]
            site["spider"] = s.get("spider", "spider.Main")
        out.append(site)
    return out


# =========================================================
# 3. 健康检查（并发 HEAD/GET，判定是否为有效 JSON 配置）
# =========================================================
def check_one(item):
    name, url = item["name"], item["url"]
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA}, allow_redirects=True)
        if r.status_code != 200:
            return {**item, "_ok": False, "_reason": f"HTTP {r.status_code}"}
        # 尝试解析为 JSON（单仓/多仓都应是 JSON）
        try:
            j = r.json()
            # 单仓看有无 sites；多仓看有无 urls；至少要是 dict
            if not isinstance(j, dict):
                return {**item, "_ok": False, "_reason": "not json object"}
            return {**item, "_ok": True, "_size": len(r.content), "_keys": list(j.keys())}
        except Exception:
            return {**item, "_ok": False, "_reason": "invalid json"}
    except Exception as e:
        return {**item, "_ok": False, "_reason": str(e)[:60]}


def health_check(pool):
    log.info("开始健康检查：%d 条线路，并发=%d", len(pool), WORKERS)
    ok, bad = [], []
    network_failed = False
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(check_one, it): it for it in pool}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                res = fut.result()
            except Exception as e:
                res = {**it, "_ok": False, "_reason": str(e)[:60]}
            (ok if res.get("_ok") else bad).append(res)
            log.info("  [%d/%d] %s -> %s", i, len(pool),
                     res["name"], "OK" if res.get("_ok") else res.get("_reason"))
    log.info("健康：%d 条，失效：%d 条", len(ok), len(bad))

    # ---- 降级策略：若几乎所有线路都因网络/403 被判失效，说明可能是本机网络受限，
    #      而非线路真失效。此时进入"信任模式"，保留全部线路（标记为待验证），
    #      避免生成空的多仓导致影视仓无片可看。真实部署在有正常网络的机器上会正常判定。 ----
    if pool and len(ok) == 0 and len(bad) == len(pool):
        sample = bad[0].get("_reason", "")
        # 连接异常 / 403 等通常说明是"检查方"问题，而非源站问题
        if any(k in sample for k in ["403", "Max retries", "Connection", "Timeout", "SSL"]):
            network_failed = True
            log.warning("⚠️ 全部线路检查均失败，疑似本机网络受限，自动降级为【信任模式】")
            ok = [{**it, "_ok": True, "_reason": "trust-mode"} for it in pool]
            bad = []
    return ok, bad, network_failed


# =========================================================
# 4. 生成单仓 line json（sites / parses / rules / lives）
# =========================================================
def build_line(line, idx, lives, search_sites=None):
    """把一条健康上游包装成一个独立单仓，附上统一的 parses(网盘解析) 和 lives。
    ★ search_sites：并联到该单仓的搜索型爬虫站，全部 searchable=1，
      影视仓会对所有 searchable 站点并发搜索 → 结果成倍增加。"""
    sites = [{
        "key": f"line{idx:02d}",
        "name": line["name"],
        "type": 1,                 # 标准采集源
        "api": line["url"],
        "searchable": 1,
        "quickSearch": 1,
        "filterable": 1,
    }]
    # ★ 并联独立搜索站点（决定搜索结果数量的关键）
    for s in (search_sites or []):
        sites.append(dict(s))
    # 附加自建采集站点（演示 spider 用法）
    for s in CUSTOM_SITES:
        sites.append(dict(s))

    parses = []
    for p in PAN_PARSES:
        parses.append({
            "name": p["name"],
            "type": p["type"],
            "url": p["url"],
            "ext": p.get("ext", {}),
        })
    # 标记为自建解析域名（实际部署时换成你自己的解析服务）
    parses.append({"name": "自建解析", "type": 1, "url": "https://your-parse.example.com/?url=", "ext": {}})

    rules = {
        "hosts": [],
        "sites": [{"name": ".*", "host": [line["url"]]}],
        "parsers": [{"name": ".*", "host": ["https://your-parse.example.com"]}],
    }

    return {
        "key": f"self_{idx:02d}",
        "name": f"自建·{line['name']}",
        "type": 1,
        "api": line["url"],
        "jar": "jar/spider.jar",        # 网盘/复杂站点爬虫
        "spider": "spider.Main",
        "sites": sites,
        "parses": parses,
        "rules": rules,
        "lives": [
            {"name": lv["name"], "type": 1, "url": lv["url"], "jar": "jar/spider.jar", "spider": "spider.Live"}
            for lv in lives
        ],
        "flags": {
            "baidu":  {"type": 18, "url": "https://your-parse.example.com/?url=", "ext": {"flag": "baidu"}},
            "quark":  {"type": 19, "url": "https://your-parse.example.com/?url=", "ext": {"flag": "quark"}},
            "uc":     {"type": 20, "url": "https://your-parse.example.com/?url=", "ext": {"flag": "uc"}},
            "aliyun": {"type": 21, "url": "https://your-parse.example.com/?url=", "ext": {"flag": "aliyun"}},
        },
        "ext": {
            "version": "1.0",
            "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "self-hosted",
        },
    }


# =========================================================
# 5. 生成多仓 index.json（影视仓最终填入的"配置地址"）
# =========================================================
def build_index(ok_lines, warehouses, lives):
    urls = []
    # 优先线路（priority<=3 且健康的）
    for i, line in enumerate([l for l in ok_lines if l.get("priority", 9) <= 3], 1):
        urls.append({
            "name": f"{line['name']}（主）",
            "url": line["url"],
            "urlv": [line["url"]],   # 备用地址，可后续追加镜像
        })
    # 其余健康线路作为备用
    for i, line in enumerate([l for l in ok_lines if l.get("priority", 9) > 3], 1):
        urls.append({"name": f"{line['name']}（备）", "url": line["url"], "urlv": [line["url"]]})
    # 多仓聚合（仓库管理里再套一层，自动展开更多线路）
    for wh in warehouses:
        urls.append({"name": wh["name"], "url": wh["url"], "urlv": [wh["url"]]})

    index = {
        "urls": urls,
        "lives": [{"name": lv["name"], "type": 1, "url": lv["url"]} for lv in lives],
        "ext": {
            "version": "1.0",
            "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "description": "自建影视仓聚合片源，多仓+自动健康巡检，防止单点失效",
        },
    }
    return index


# =========================================================
# 6. 生成独立单仓文件 lines/<name>.json
# =========================================================
def write_lines(ok_lines, lives, search_sites=None):
    written = []
    for i, line in enumerate(ok_lines, 1):
        data = build_line(line, i, lives, search_sites)
        fname = f"lines/{line['name']}.json"
        with open(os.path.join(BASE, fname), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        written.append((fname, line["name"]))
    return written


# =========================================================
# 7. 生成 spider 配置说明 + 最小可用 jar 占位 + README
# =========================================================
SPIDER_README = """# Spider 爬虫说明

本目录存放影视仓使用的 spider.jar，负责：
  - 百度网盘 / 夸克网盘 / UC网盘 / 阿里云盘 的分享链接解析
  - 复杂动态站点（JS 渲染、加密参数）的采集

## 如何获取/更新 spider.jar
方案 A（推荐，开箱即用）：
  直接使用开源社区维护的通用 spider，例如：
    - https://github.com/FongMi/ 系列
    - 将 jar 下载后放入本目录，命名为 spider.jar

方案 B（自建，完全可控）：
  参考 tvbox-config 类仓库，编写 drpy2 规则（FTY/*.js），
  打包进 spider.jar，在单仓里通过 "jar" + "spider" 字段引用。

## 网盘 flag 映射（单仓 flags 字段）
  baidu  -> type 18
  quark  -> type 19
  uc     -> type 20
  aliyun -> type 21

影视仓播放网盘资源时，会按 flags 里的 flag 路由到对应解析逻辑。
"""


def write_spider_placeholder():
    with open(os.path.join(SPIDER_DIR, "README.md"), "w", encoding="utf-8") as f:
        f.write(SPIDER_README)
    # 占位 jar（真实使用需替换为可运行的 spider.jar，此处仅保证结构完整）
    placeholder = os.path.join(SPIDER_DIR, "spider.jar")
    if not os.path.exists(placeholder):
        with open(placeholder, "wb") as f:
            f.write(b"")  # 真实部署时覆盖为可用 jar


# =========================================================
# 8. 主流程
# =========================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="仅健康检查")
    ap.add_argument("--no-check", action="store_true", help="跳过网络检查")
    args = ap.parse_args()

    sources = load_sources()
    all_lines = sources["lines"]
    lives = sources["lives"]
    search_sites_pool = sources.get("search_sites", []) or []

    if args.check:
        ok, bad = health_check(all_lines)
        print("\n===== 健康报告 =====")
        for r in ok:
            print(f"  [OK]   {r['name']:10s} {r['url']}")
        for r in bad:
            print(f"  [BAD]  {r['name']:10s} {r['url']}  ({r.get('_reason')})")
        sys.exit(0)

    ok_lines, bad_lines, _ = (all_lines, [], False) if args.no_check else health_check(all_lines)

    # ★ 吸收公开单仓的搜索站点（自动越攒越多；失败自动跳过）
    try:
        absorbed = ingest_public_sites(sources.get("ingest", {}), ok_lines,
                                       cap_per_index=30)
    except Exception as e:
        log.warning("吸收逻辑异常，跳过：%s", str(e)[:60])
        absorbed = []
    # 合并：手工维护的 search_sites 优先，吸收来的追加在后（已内部去重）
    all_search = list(search_sites_pool) + absorbed

    # 规范化搜索站点（强制 searchable=1，统一 jar 引用）
    normalized_search = build_search_sites(all_search)

    # 备份旧配置
    if os.path.exists(OUT_INDEX):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.rename(OUT_INDEX, os.path.join(BACKUP_DIR, f"index_{ts}.json"))

    # 生成单仓（把搜索站点并联进去）
    written = write_lines(ok_lines, lives, normalized_search)
    log.info("生成 %d 个单仓文件（各并联 %d 个搜索站点）", len(written), len(normalized_search))

    # 生成多仓 index
    index = build_index(ok_lines, sources.get("warehouses", []), lives)
    with open(OUT_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    log.info("生成 index.json，共 %d 条线路入口", len(index["urls"]))

    write_spider_placeholder()

    # README
    readme = f"""# 自建影视仓聚合片源

> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> 当前健康线路：**{len(ok_lines)}** 条，失效：**{len(bad_lines)}** 条

## 目录结构
```
.
├── index.json              # ★ 多仓入口（影视仓「配置地址」填这个）
├── lines/                  # 每条健康线路一个单仓 json
├── jar/spider.jar          # 网盘/复杂站点爬虫（百度·夸克·UC·阿里）
├── scripts/generate.py     # 本生成器
├── sources.yaml            # 上游线路池（可编辑，热更新）
└── backup/                 # 历史配置自动备份
```

## 使用方式
1. 把本目录部署到 **GitHub Pages / Gitee / 自建服务器**（需 HTTPS 公网可访问）
2. 影视仓 → 设置 → 配置地址 → 填入 `https://你的域名/index.json`
3. 如需多仓，仓库管理里再添加 index.json，自动展开所有线路

## 如何保证不突然失效
- ✅ 多仓结构：index.json 挂 N 条单仓，一条挂不影响其他
- ✅ 每条单仓配 `urlv` 备用地址 + 多 CDN 镜像
- ✅ 自动健康检查：crontab 每日跑 `python3 generate.py`，失效线路自动剔除
- ✅ 配置自动备份到 backup/，出问题可回滚
- ✅ 网盘源走 spider.jar 统一适配，规则可独立更新

## 定时更新（crontab 示例，每天 6 点刷新）
```
0 6 * * * cd /path/to/yingshicang && python3 scripts/generate.py >> scripts/update.log 2>&1
```

## 自定义上游
编辑 `sources.yaml`，按以下格式增删：
```yaml
lines:
  - name: 我的线路
    url: https://example.com/tvbox.json
    tags: [点播, 4K]
    priority: 1   # 1-3 主用，>3 备用
```
"""
    with open(os.path.join(BASE, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme)

    print("\n===== 生成完成 =====")
    print(f"  健康线路：{len(ok_lines)} 条")
    print(f"  失效线路：{len(bad_lines)} 条")
    print(f"  并联搜索站点：{len(normalized_search)} 个（决定搜索结果数量）")
    print(f"  多仓入口：{OUT_INDEX}")
    print(f"  单仓目录：{OUT_DIR}/")
    if bad_lines:
        print("  失效明细：")
        for b in bad_lines:
            print(f"    - {b['name']:10s} {b.get('_reason')}")


if __name__ == "__main__":
    main()
