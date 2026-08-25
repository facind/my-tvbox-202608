#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影视仓 / TVBox 自建聚合片源 生成器（v3 - UA 模拟 + 二次探测）
==================================================================
相较 v2 的改进：
  1) 请求头完整模拟 TVBox / FongMi 客户端（含 X-Requested-With 包名），
     避免被源站按 UA 区分返回 HTML；
  2) 对判定为 NAV（导航页/存活页）的源自动做"播放器模式二次探测"，
     若二次请求返回合法 TVBox JSON -> 升级为 VALID 并生成独立单仓；
  3) 支持 sources.yaml 单条加 `skip_check: true` 强制保留；
  4) 抑制 urllib3 InsecureRequestWarning（本地 jar 自检 127.0.0.1 场景）。
"""
import json, os, sys, time, warnings, logging, argparse, re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 本地 jar 自检会产生 127.0.0.1 自签名警告，属无害 -> 抑制
warnings.filterwarnings("ignore", category=Warning)

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

# 完整模拟 TVBox / FongMi 客户端请求头（首次探测用）
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11; TVBox) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Version/4.0 Chrome/94.0 Safari/537.36",
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "com.fongmi.android.tv",
}
# 播放器模式 UA（二次探测用，部分源靠此返回纯 JSON）
PLAYER_HEADERS = dict(HEADERS)
PLAYER_HEADERS["User-Agent"] = "TVBox/1.0.0 (Linux; Android 11; TVBox) AppleWebKit/537.36"

TIMEOUT = 15
WORKERS = 20
RETRY = 1

# 域名售卖页 / 错误页特征（命中即便 HTTP 200 也判 dead）
DEAD_KEYWORDS = [
    "域名售卖", "domain for sale", "afternic", "is for sale", "出售域名",
    "page not found", "404 not found", "access denied",
    "The requested URL could not be retrieved", "ERR_CONNECTION", "ERR_EMPTY_RESPONSE",
    "NoSuchBucket", "CNAMECrossDomain", "site not found", "dreamhost",
    "site is not found", "this site can't be reached",
]

# TVBox 单仓 JSON 特征字段（满足其一即视为合法单仓）
TVBOX_JSON_KEYS = ["sites", "spider", "storeHouse", "urls", "video", "list", "class"]


# =========================================================
# 1. 加载 sources.yaml
# =========================================================
def load_sources():
    if os.path.exists(SRC_YAML):
        with open(SRC_YAML, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        log.info("从 sources.yaml 加载上游配置")
        return {
            "lines": data.get("lines") or [],
            "warehouses": data.get("warehouses", []),
            "lives": data.get("lives", []),
            "search_sites": data.get("search_sites", []),
            "ingest": data.get("ingest", {"enabled": False, "index_urls": []}),
        }
    log.error("未找到 sources.yaml！")
    sys.exit(1)


# =========================================================
# 2. 吸收公开单仓 sites
# =========================================================
def _fetch_json(url, timeout=15, headers=None):
    try:
        r = requests.get(url, timeout=timeout, headers=headers or HEADERS, allow_redirects=True, verify=False)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("  吸收失败 %s : %s", url, str(e)[:50])
    return None


def _collect_sites_from_index(obj, acc, seen, cap, only_searchable):
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
        acc.append(dict(s))
        if len(acc) >= cap:
            return True
    return False


def ingest_public_sites(ingest_cfg, base_pool, cap_per_index=30):
    if not ingest_cfg or not ingest_cfg.get("enabled"):
        return []
    index_urls = ingest_cfg.get("index_urls", []) or []
    only_searchable = ingest_cfg.get("only_searchable", True)
    prefer_stable = ingest_cfg.get("prefer_stable", True)
    cap = cap_per_index or 30

    seen = set()
    for line in base_pool:
        seen.add(line.get("url"))
        seen.add(line.get("key"))
    absorbed = []

    log.info("★ 开始吸收公开索引：%d 个索引地址", len(index_urls))
    for url in index_urls:
        obj = _fetch_json(url)
        if isinstance(obj, dict) and "urls" in obj and isinstance(obj["urls"], list):
            for u in obj["urls"][:cap]:
                sub_url = u.get("url") if isinstance(u, dict) else u
                sub_key = u.get("key") if isinstance(u, dict) else None
                if not sub_url or sub_url in seen or (sub_key and sub_key in seen):
                    continue
                sub = _fetch_json(sub_url)
                if isinstance(sub, dict):
                    if _collect_sites_from_index(sub, absorbed, seen, cap, only_searchable):
                        break
        elif isinstance(obj, dict):
            _collect_sites_from_index(obj, absorbed, seen, cap, only_searchable)

    if prefer_stable:
        absorbed.sort(key=lambda s: 0 if s.get("searchable") else 1)
    log.info("★ 本次吸收到 %d 个新搜索站点（已去重）", len(absorbed))
    return absorbed


# =========================================================
# 3. 规范化搜索站点
# =========================================================
def build_search_sites(all_search_sites):
    out = []
    seen = set()
    for i, s in enumerate(all_search_sites, 1):
        key = s.get("key") or f"search_{i:02d}"
        if key in seen:        # 关键：按 key 去重，避免跨池重复吸收（你之前踩过的真实 bug）
            continue
        seen.add(key)
        site = {
            "key": key,
            "name": s.get("name") or f"搜索站{i}",
            "type": s.get("type", 1),
            "api": s["api"],
            "searchable": 1,
            "quickSearch": s.get("quickSearch", 1),
            "filterable": s.get("filterable", 1),
        }
        if s.get("jar"):
            site["jar"] = s["jar"]
            site["spider"] = s.get("spider", "spider.Main")
        out.append(site)
    return out


# =========================================================
# 4. 三档健康检查 + 二次探测（核心）
# =========================================================
def _is_dead_page(text):
    lower = text[:3000].lower()
    for kw in DEAD_KEYWORDS:
        if kw.lower() in lower:
            return kw
    return None


def _looks_like_tvbox_json(j):
    """判断解析出的 dict/list 是否像 TVBox 单仓结构"""
    if isinstance(j, list):
        return len(j) > 0
    if isinstance(j, dict):
        return any(k in j for k in TVBOX_JSON_KEYS)
    return False


def _fetch_with_retry(url, headers=None):
    last_err = ""
    for attempt in range(RETRY + 1):
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=headers or HEADERS,
                             allow_redirects=True, verify=False)
            return r, ""
        except requests.exceptions.Timeout:
            last_err = "timeout"
        except requests.exceptions.ConnectionError:
            last_err = "connection refused"
        except Exception as e:
            last_err = str(e)[:60]
        if attempt < RETRY:
            time.sleep(1)
    return None, last_err


def check_one(item):
    """三档判定：valid / nav / dead。nav 会再做播放器模式二次探测。"""
    name, url = item["name"], item["url"]

    # skip_check 强制保留为 valid（信任用户声明）
    if item.get("skip_check"):
        return {**item, "_status": "valid", "_reason": "skip_check", "_size": 0}

    r, err = _fetch_with_retry(url)
    if r is None:
        return {**item, "_status": "dead", "_reason": err or "unknown error"}

    if r.status_code != 200:
        return {**item, "_status": "dead", "_reason": f"HTTP {r.status_code}"}

    content = r.text or ""

    # 售卖/错误页特征检测
    dead_kw = _is_dead_page(content)
    if dead_kw:
        return {**item, "_status": "dead", "_reason": f"dead page ({dead_kw})"}

    # 首次探测尝试解析 JSON
    try:
        j = r.json()
        if _looks_like_tvbox_json(j):
            return {**item, "_status": "valid", "_reason": "tvbox json", "_size": len(r.content)}
    except Exception:
        pass  # 不是 JSON -> 走下面的 nav + 二次探测

    # 非 JSON 但内容充实 -> 先标 nav，再做播放器模式二次探测
    if len(content.strip()) > 200:
        r2, _ = _fetch_with_retry(url, headers=PLAYER_HEADERS)
        if r2 is not None and r2.status_code == 200:
            try:
                j2 = r2.json()
                if _looks_like_tvbox_json(j2):
                    return {**item, "_status": "valid", "_reason": "upgraded by player-UA",
                            "_size": len(r2.content)}
            except Exception:
                pass
        return {**item, "_status": "nav", "_reason": "html page (alive, not json)",
                "_size": len(r.content)}

    return {**item, "_status": "dead", "_reason": "empty or too short response"}


def health_check(pool):
    log.info("开始健康检查（三档模式）：%d 条线路，并发=%d，超时=%ds", len(pool), WORKERS, TIMEOUT)
    valid, nav, dead = [], [], []

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(check_one, it): it for it in pool}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                res = fut.result()
            except Exception as e:
                res = {**futs[fut], "_status": "dead", "_reason": str(e)[:60]}
            status = res.get("_status", "dead")
            if status == "valid":
                valid.append(res)
            elif status == "nav":
                nav.append(res)
            else:
                dead.append(res)
            tag = {"valid": "✅VALID", "nav": "⚠️ NAV ", "dead": "❌ DEAD"}.get(status, "❓")
            log.info("  [%d/%d] %s %s -> %s (%s)", i, len(pool), tag, res["name"],
                     res.get("_reason", ""), res.get("url", ""))

    log.info("检查结果：VALID=%d, NAV=%d, DEAD=%d", len(valid), len(nav), len(dead))

    # 信任模式降级：全部失败时全部当 nav 保留
    if len(valid) == 0 and len(nav) == 0 and len(pool) > 0:
        log.warning("⚠️ 所有线路检查均失败，疑似网络受限，自动降级为【信任模式】")
        nav = [{**it, "_status": "nav", "_reason": "trust-mode"} for it in pool]
        dead = []

    return valid, nav, dead


# =========================================================
# 5. 生成单仓 line json（仅 valid 类）
# =========================================================
PAN_PARSES = [
    {"name": "百度网盘", "type": 18, "url": "https://your-parse.example.com/?url=", "ext": {"flag": "baidu"}},
    {"name": "夸克网盘", "type": 19, "url": "https://your-parse.example.com/?url=", "ext": {"flag": "quark"}},
    {"name": "UC网盘",   "type": 20, "url": "https://your-parse.example.com/?url=", "ext": {"flag": "uc"}},
    {"name": "阿里云盘", "type": 21, "url": "https://your-parse.example.com/?url=", "ext": {"flag": "aliyun"}},
    {"name": "万能解析", "type": 24, "url": "https://your-parse.example.com/?url=", "ext": {"flag": "universal"}},
]


def build_line(line, idx, lives, search_sites=None):
    sites = [{
        "key": f"line{idx:02d}",
        "name": line["name"],
        "type": 1,
        "api": line["url"],
        "searchable": 1,
        "quickSearch": 1,
        "filterable": 1,
    }]
    for s in (search_sites or []):
        sites.append(dict(s))

    parses = [{"name": p["name"], "type": p["type"], "url": p["url"], "ext": p.get("ext", {})}
               for p in PAN_PARSES]

    return {
        "key": f"self_{idx:02d}",
        "name": f"自建·{line['name']}",
        "type": 1,
        "api": line["url"],
        "sites": sites,
        "parses": parses,
        "lives": [{"name": lv["name"], "type": 1, "url": lv["url"]} for lv in lives],
        "ext": {"version": "1.0", "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": "self-hosted"},
    }


def write_lines(valid_lines, lives, search_sites=None):
    written = []
    for i, line in enumerate(valid_lines, 1):
        data = build_line(line, i, lives, search_sites)
        fname = f"lines/{line['name']}.json"
        with open(os.path.join(BASE, fname), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        written.append((fname, line["name"]))
    return written


# =========================================================
# 6. 生成多仓 index.json（valid + nav 全部进 urls）
# =========================================================
def build_index(valid_lines, nav_lines, warehouses, lives):
    urls = []
    all_alive = valid_lines + nav_lines
    all_alive.sort(key=lambda x: x.get("priority", 9))

    for line in all_alive:
        priority = line.get("priority", 9)
        label = "主" if priority <= 3 else "备"
        urls.append({"name": f"{line['name']}（{label}）", "url": line["url"], "urlv": [line["url"]]})

    for wh in warehouses:
        urls.append({"name": wh["name"], "url": wh["url"], "urlv": [wh["url"]]})

    return {
        "urls": urls,
        "lives": [{"name": lv["name"], "type": 1, "url": lv["url"]} for lv in lives],
        "ext": {"version": "1.0", "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "description": "自建影视仓聚合片源，多仓+自动健康巡检，防止单点失效"},
    }


def write_spider_placeholder():
    os.makedirs(SPIDER_DIR, exist_ok=True)
    placeholder = os.path.join(SPIDER_DIR, "spider.jar")
    if not os.path.exists(placeholder):
        with open(placeholder, "wb") as f:
            f.write(b"")


# =========================================================
# 7. 主流程
# =========================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="仅健康检查")
    ap.add_argument("--no-check", action="store_true", help="跳过网络检查")
    args = ap.parse_args()

    sources = load_sources()
    all_lines = sources["lines"]
    lives = sources["lives"]

    if args.check or args.no_check:
        if args.no_check:
            valid, nav, dead = all_lines, [], []
            log.info("--no-check 模式：全部当作 valid")
        else:
            valid, nav, dead = health_check(all_lines)

        print("\n===== 健康报告（三档）=====")
        print(f"  ✅ VALID: {len(valid)} 条")
        for r in valid:
            print(f"     {r['name']:12s} {r['url']}  ({r.get('_reason','')})")
        print(f"  ⚠️  NAV : {len(nav)} 条")
        for r in nav:
            print(f"     {r['name']:12s} {r['url']}  ({r.get('_reason','')})")
        print(f"  ❌ DEAD: {len(dead)} 条")
        for r in dead:
            print(f"     {r['name']:12s} {r['url']}  ({r.get('_reason','')})")
        if not args.check:  # --no-check 继续生成
            pass
        else:
            return

    if args.no_check:
        valid, nav, dead = all_lines, [], []
    else:
        valid, nav, dead = health_check(all_lines)

    # 吸收公开站点
    try:
        absorbed = ingest_public_sites(sources.get("ingest", {}), valid + nav, cap_per_index=30)
    except Exception as e:
        log.warning("吸收逻辑异常，跳过：%s", str(e)[:60])
        absorbed = []
    search_pool = list(sources.get("search_sites", []) or []) + absorbed
    normalized_search = build_search_sites(search_pool)

    # 备份旧 index
    if os.path.exists(OUT_INDEX):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.rename(OUT_INDEX, os.path.join(BACKUP_DIR, f"index_{ts}.json"))

    # 清理旧 lines，仅重建 valid
    for fn in os.listdir(OUT_DIR):
        if fn.endswith(".json"):
            os.remove(os.path.join(OUT_DIR, fn))
    written = write_lines(valid, lives, normalized_search)
    log.info("生成 %d 个单仓文件（valid 类），各并联 %d 个搜索站点", len(written), len(normalized_search))

    index = build_index(valid, nav, sources.get("warehouses", []), lives)
    with open(OUT_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    log.info("生成 index.json，共 %d 条线路入口（%d valid + %d nav + %d 多仓）",
             len(index["urls"]), len(valid), len(nav), len(sources.get("warehouses", [])))

    write_spider_placeholder()

    print("\n===== 生成完成 =====")
    print(f"  ✅ VALID（生成单仓）: {len(valid)} 条")
    print(f"  ⚠️  NAV（直接进index）: {len(nav)} 条")
    print(f"  ❌ DEAD（已剔除）:     {len(dead)} 条")
    print(f"  并联搜索站点：{len(normalized_search)} 个")
    print(f"  多仓入口：{OUT_INDEX}")
    if dead:
        print("  被剔除的线路：")
        for d in dead:
            print(f"    - {d['name']:12s} {d.get('_reason')}")


if __name__ == "__main__":
    main()
