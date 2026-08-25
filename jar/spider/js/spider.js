/**
 * CatVodSpider · 通用 JS 规则适配层（v2 · 支持扫码登录）
 * ==========================================================
 * 升级点（相比 v1 骨架）：
 *   1) 统一扫码登录契约：getQrCodeToken / checkLoginStatus / getCookie
 *      - 壳子(影视仓/TVBox) 调用 playerContent 时，若 spider 需要鉴权，
 *        返回 { auth: { qr: "...", token: "..." } }，壳子据此在电视端画二维码；
 *      - 壳子轮询 checkLoginStatus(token)，登录成功后 spider 缓存 cookie 到本地，
 *        后续同网盘资源免扫码直连播放。
 *   2) 本地缓存：cookie / refresh_token 持久化（Java 侧注入 __store__ / __load__）。
 *   3) 兼容无扫码壳子：返回普通直链，降级播放。
 *
 * 网盘 flag 路由：baidu=18  quark=19  uc=20  aliyun=21  universal=24
 *
 * 参考：FongMi/CatVodSpider (MIT) · js 插件设计思想
 */

(function (global) {
    'use strict';

    var Log = {
        info: function (m) { print('[spider][info] ' + m); },
        err:  function (m) { print('[spider][err]  ' + m); }
    };

    /** 读配置（Java 侧注入 __config__） */
    function getConfig() {
        try { return global.__config__ ? JSON.parse(global.__config__()) : {}; }
        catch (e) { return {}; }
    }

    /** 本地持久化（Java 侧注入 __store__/__load__，无则内存兜底） */
    var memStore = {};
    function store(key, val) {
        try { global.__store__ ? global.__store__(key, JSON.stringify(val)) : (memStore[key] = JSON.stringify(val)); } catch (e) {}
    }
    function load(key) {
        try {
            var s = global.__load__ ? global.__load__(key) : memStore[key];
            return s ? JSON.parse(s) : null;
        } catch (e) { return null; }
    }

    /** HTTP GET/POST（Java 侧注入） */
    function fetchText(url, headers) {
        try { return global.__fetch__(url, JSON.stringify(headers || {})); }
        catch (e) { Log.err('fetch failed: ' + url + ' | ' + e); return ''; }
    }
    function postJson(url, body, headers) {
        try { return global.__post__ ? global.__post__(url, JSON.stringify(body || {}), JSON.stringify(headers || {})) : ''; }
        catch (e) { return ''; }
    }

    /** 正则提取 */
    function matchAll(text, re) {
        var out = [], m, reg = new RegExp(re, 'g');
        while ((m = reg.exec(text)) !== null) out.push(m);
        return out;
    }

    /**
     * 构造"需要扫码"的返回结构（壳子识别 auth 字段后弹二维码）
     * qrUrl: 二维码内容（通常是网盘扫码登录 ticket 或 oauth url）
     * token: 轮询标识，壳子 checkLoginStatus 时原样回传
     */
    function authQr(qrUrl, token, extra) {
        var a = { auth: { qr: qrUrl, token: token || '' } };
        if (extra) for (var k in extra) if (extra.hasOwnProperty(k)) a.auth[k] = extra[k];
        return a;
    }

    /**
     * 基础 Spider 类（网盘规则继承）
     * ----------------------------------------------------------------
     * 子类约定方法：
     *   getQrCodeToken()        -> {qr, token}        生成扫码凭证
     *   checkLoginStatus(token) -> {cookie, ...} | null  轮询登录结果
     *   getCookie()             -> string              读取已缓存登录态
     *   setCookie(ck)                               写入缓存
     *   parseShare(url, pwd)    -> [{vod_id, vod_name}]  分享链接 -> 文件列表
     *   getPlayUrl(fileId)      -> string                文件 -> 直链
     */
    var BaseSpider = {
        siteKey: 'base',
        siteName: 'BaseSpider',
        api: '',
        flag: '',

        homeContent: function (filter) { return '{}'; },
        categoryContent: function (tid, pg) { return '{}'; },

        searchContent: function (key) {
            Log.info(this.siteName + ' search: ' + key);
            return JSON.stringify({ list: [] });
        },
        detailContent: function (ids) {
            return JSON.stringify({ list: [] });
        },

        /** 默认播放解析：无鉴权 -> 直返 id（universal） */
        playerContent: function (flag, id) {
            Log.info('player flag=' + flag + ' id=' + id);
            var t = ({ baidu: 18, quark: 19, uc: 20, aliyun: 21 })[flag] || 24;
            return JSON.stringify({ url: id, header: '', type: t });
        },

        // ---- 扫码契约默认实现（子类按需覆盖）----
        getQrCodeToken: function () { return null; },
        checkLoginStatus: function (token) { return null; },
        getCookie: function () { return load(this.flag + '_cookie') || ''; },
        setCookie: function (ck) { if (ck) store(this.flag + '_cookie', ck); }
    };

    /** 注册表 */
    var registry = {};

    function register(spider) {
        if (spider && spider.siteKey) {
            registry[spider.siteKey] = spider;
            Log.info('registered: ' + spider.siteKey + ' (' + spider.siteName + ')');
        }
    }

    /** 按 flag / siteKey 获取 spider */
    function getSpider(flag) {
        if (registry[flag]) return registry[flag];
        for (var k in registry) {
            if (registry.hasOwnProperty(k) && registry[k].flag === flag) return registry[k];
        }
        return BaseSpider;
    }

    global.Spider = {
        register: register,
        get: getSpider,
        all: function () { return Object.keys(registry); },
        // 供 Java 侧反射的统一入口（扫码流程）
        getQrCodeToken: function (flag) {
            var sp = getSpider(flag);
            var r = sp && sp.getQrCodeToken ? sp.getQrCodeToken() : null;
            return JSON.stringify(r || {});
        },
        checkLoginStatus: function (flag, token) {
            var sp = getSpider(flag);
            var r = sp && sp.checkLoginStatus ? sp.checkLoginStatus.call(sp, token) : null;
            if (r && r.cookie) sp.setCookie.call(sp, r.cookie);
            return JSON.stringify(r || {});
        },
        fetchText: fetchText,
        postJson: postJson,
        matchAll: matchAll,
        authQr: authQr,
        store: store,
        load: load,
        getConfig: getConfig,
        Log: Log,
        BaseSpider: BaseSpider
    };

})(this);
