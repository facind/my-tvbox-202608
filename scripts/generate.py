#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影视仓 / TVBox 自建聚合片源 生成器（v4 - 输出 TVBox 标准单文件）
==================================================================
相较 v3 的核心改动：
  ★ index.json 现在直接输出 TVBox 标准规范格式（扁平单配置），
    可被任意 TVBox / 影视仓 客户端「配置地址」直接解析：
        {
          "sites":   [ {key, name, type, api, ...}, ... ],   # 全部线路展平
          "parses":  [ ... ],
          "spider":  "...",
          "lives":   [ ... ]
        }
    不再输出旧版的 {urls:[...]} 多仓清单格式（旧格式客户端不递归、易整体解析失败）。

  ★ 内容全部保留、一个不剔除：
      - 每个 line（valid + nav 全部进）都展成 sites 里的独立条目；
      - 主链 url + 备用链 urlv 各自成一条（key 加后缀区分）；
      - 本身是"多仓链接"（返回含 urls/storeHouse 的 JSON）的条目，
        会递归展开其内部子站点，展开失败则保留入口条目本身；
      - 无法拉取/非 JSON 的条目也保留为 site（客户端点进去该源无内容，
        但不会导致整个配置崩溃）。

  其余逻辑（UA 模拟、三档健康检查、二次探测、公开站点吸收、备份、
  lines/、jar/）与 v3 完全一致，未做删减。
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
# 4. 三档健康检查 + 二次探测（核心，与 v3 一致）
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
# 5. 生成单仓 line json（仅 valid 类，保留与 v3 一致）
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
# 6. 【核心改动】生成 TVBox 标准单文件 index.json
# =========================================================
def _safe_key(s):
    """
    把任意字符串（含中文）规整成合法的 site key：
      - 保留字母数字下划线；
      - 中文等多字节字符用 unicode 码点转成 _uXXXX，保证唯一可追溯；
      - 空结果兜底为 'site'。
    例：'饭太硬' -> '饭太硬'（字母数字保留，中文保留）-> 为兼容 TVBox 仅取 ascii 部分，
        中文兜底转 hex，最终如 'u9965u592a' 这类稳定 key。
    """
    s = str(s).strip()
    if not s:
        return "site"
    # 优先保留 ascii 字母数字，非 ascii 部分用其 utf-16 码点拼成稳定字符串
    out = []
    for ch in s:
        if re.match(r"[a-z0-9_-]", ch, re.I):
            out.append(ch.lower())
        elif ord(ch) > 127:
            out.append("_u%x" % ord(ch))
        else:
            out.append("_")
    key = re.sub(r"_+", "_", "".join(out)).strip("_")
    return key or "site"


def _fetch_remote_config(url):
    """尝试拉取一个 url，若返回 TVBox 风格配置 dict 则返回，否则 None"""
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True, verify=False)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, dict) and ("sites" in j or "urls" in j or "storeHouse" in j):
                return j
    except Exception:
        pass
    return None


def _expand_warehouse(url, name, seen, sites_out, depth=0):
    """
    递归展开一个"多仓链接"：
      - 若该 url 返回含 sites 的标准配置 -> 直接把 sites 展平加入；
      - 若返回含 urls/storeHouse 的多仓清单 -> 遍历其每个子 url 递归（depth 限 1 层，防失控）；
      - 拉取失败 / 非 JSON -> 返回 False，由调用方保留入口条目本身。
    seen: 已加入的 site key 集合（去重）。
    """
    cfg = _fetch_remote_config(url)
    if not cfg:
        return False

    # 情况 A：本身就是标准单仓（有 sites）
    if "sites" in cfg and isinstance(cfg["sites"], list):
        added = 0
        for s in cfg["sites"]:
            if not isinstance(s, dict):
                continue
            key = s.get("key") or s.get("api") or s.get("name")
            if not key:
                continue
            key = _safe_key(key)
            # 防同名：追加序号
            base_key = key
            n = 1
            while key in seen:
                key = f"{base_key}_{n}"
                n += 1
            seen.add(key)
            site = dict(s)
            site["key"] = key
            sites_out.append(site)
            added += 1
        log.info("     ↳ 展开 [%s] 获得 %d 个站点", name, added)
        return True

    # 情况 B：是多仓清单（urls / storeHouse），递归一层
    if depth < 1:
        sub_list = cfg.get("urls") or cfg.get("storeHouse") or []
        ok_any = False
        for u in sub_list:
            sub_url = u.get("url") if isinstance(u, dict) else u
            sub_name = u.get("name", sub_url) if isinstance(u, dict) else sub_url
            if not sub_url:
                continue
            if _expand_warehouse(sub_url, sub_name, seen, sites_out, depth + 1):
                ok_any = True
        if ok_any:
            return True
    return False


def _line_to_sites(line, idx, seen, sites_out, parses_out, spider_holder):
    """
    把一个 line 条目（valid 或 nav）展成一条/多条 site，加入 sites_out。
      - 主链 url 作为主 site；
      - urlv 里每条备用链也各成一条（key 加 _v1/_v2 区分）；
      - 若 url 本身是多仓链接且能递归展开 -> 展开后并入 sites_out，
        同时保留主入口 site 指向该多仓 url，保证"一个不丢"。
    不剔除任何条目：拉不到/非 JSON 的也保留为 site 条目。
    """
    name = line["name"]
    main_url = line["url"]
    backups = line.get("urlv") or []

    # 先尝试当作"多仓链接"递归展开（展开成功则内部站点全部并入）
    expanded = False
    if main_url:
        # 用一个临时 list 试探，避免展开失败污染 seen
        tmp_seen = set(seen)
        tmp_sites = []
        if _expand_warehouse(main_url, name, tmp_seen, tmp_sites, depth=0):
            seen.update(tmp_seen)
            sites_out.extend(tmp_sites)
            expanded = True

    # 组装主链 + 备用链条目（即使展开了也保留入口，确保不丢）
    all_api = [(main_url, "")] + [(u, f"_v{i+1}") for i, u in enumerate(backups) if u and u != main_url]
    for api_url, suffix in all_api:
        if not api_url:
            continue
        base_key = _safe_key(name)
        key = f"{base_key}{suffix}"
        n = 1
        while key in seen:
            key = f"{base_key}{suffix}_{n}"
            n += 1
        seen.add(key)
        site = {
            "key": key,
            "name": name if not suffix else f"{name}（备用{suffix.strip('_v')}）",
            "type": 3,
            "api": api_url,
            "searchable": 1,
            "quickSearch": 1,
            "filterable": 1,
        }
        sites_out.append(site)

    # 若该 line 自带 parses（来自 line 自身配置），收集（不去重，全保留）
    if isinstance(line.get("parses"), list):
        parses_out.extend(line["parses"])


def build_index(valid_lines, nav_lines, warehouses, lives, normalized_search, dead_lines=None):
    """
    生成 TVBox 标准规范配置（扁平单文件）：
        {
          "sites":  [...全部线路展平后的站点，一个不丢...],
          "parses": [...],
          "spider": "...",
          "lives":  [...]
        }
    注意：valid / nav / dead 全部展平进 sites，一个都不剔除——
    拉不到/非 JSON 的条目至少保留其入口 site，避免"整体解析失败"。
    """
    sites = []
    parses = []
    spider = ""
    seen = set()

    # 1) 处理 lines（valid + nav + dead 全部展平，一个不剔除）
    all_lines = valid_lines + nav_lines + (dead_lines or [])
    all_lines.sort(key=lambda x: x.get("priority", 9))
    for idx, line in enumerate(all_lines, 1):
        _line_to_sites(line, idx, seen, sites, parses, None)

    # 2) 处理多仓 warehouses：当作"多仓链接"尝试递归展开内部 sites
    for wh in warehouses:
        name = wh.get("name", "多仓")
        main_url = wh.get("url")
        backups = wh.get("urlv") or []
        # 先尝试递归展开
        tmp_seen = set(seen)
        tmp_sites = []
        expanded = False
        if main_url and _expand_warehouse(main_url, name, tmp_seen, tmp_sites, depth=0):
            seen.update(tmp_seen)
            sites.extend(tmp_sites)
            expanded = True
        # 备用链/入口也保留
        all_api = [(main_url, "")] + [(u, f"_v{i+1}") for i, u in enumerate(backups) if u and u != main_url]
        for api_url, suffix in all_api:
            if not api_url:
                continue
            base_key = _safe_key(name)
            key = f"{base_key}{suffix}"
            n = 1
            while key in seen:
                key = f"{base_key}{suffix}_{n}"
                n += 1
            seen.add(key)
            sites.append({
                "key": key,
                "name": name if not suffix else f"{name}（备用{suffix.strip('_v')}）",
                "type": 3,
                "api": api_url,
                "searchable": 1,
                "quickSearch": 1,
                "filterable": 1,
            })

    # 3) 若启用公开站点吸收，把规范化后的搜索站点并入 sites 末尾
    for s in normalized_search:
        key = s.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        sites.append(dict(s))

    # 4) 组装最终标准配置
    cfg = {
        "sites": sites,
        "parses": parses,
        "spider": spider,
        "lives": [{"name": lv["name"], "type": 1, "url": lv["url"]} for lv in lives],
        "ext": {
            "version": "2.0",
            "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "description": "自建影视仓聚合片源（TVBox 标准单文件，可直接填入客户端配置地址）",
        },
    }
    return cfg


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

    # ★ 核心：生成 TVBox 标准单文件 index.json（扁平 sites，全部保留，含 dead）
    index = build_index(valid, nav, sources.get("warehouses", []), lives, normalized_search, dead_lines=dead)
    with open(OUT_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    log.info("生成 TVBox 标准 index.json：共 %d 个站点（%d valid + %d nav + %d dead保留 + %d 多仓展开 + %d 搜索站）",
             len(index["sites"]), len(valid), len(nav), len(dead),
             len(sources.get("warehouses", [])), len(normalized_search))

    write_spider_placeholder()

    print("\n===== 生成完成（TVBox 标准单文件）=====")
    print(f"  ✅ VALID（生成单仓）: {len(valid)} 条")
    print(f"  ⚠️  NAV（展平进 sites）: {len(nav)} 条")
    print(f"  ❌ DEAD（入口仍保留进 sites，不剔除）: {len(dead)} 条")
    print(f"  📦 多仓入口：{len(sources.get('warehouses', []))} 个（递归展开内部站点）")
    print(f"  🔍 并联搜索站点：{len(normalized_search)} 个")
    print(f"  📄 最终 sites 总数：{len(index['sites'])} 个")
    print(f"  📍 输出文件：{OUT_INDEX}")
    print("  —— 该 index.json 可直接填入 TVBox / 影视仓「配置地址」使用 ——")
    if dead:
        print("  （以下线路健康检查失败，未展平为站点，但配置仍可正常加载）")
        for d in dead:
            print(f"    - {d['name']:12s} {d.get('_reason')}")


if __name__ == "__main__":
    main()
