/**
 * 百度网盘 (baidu) 解析规则  v2
 * ==================================
 * flag = baidu  (type 18)
 *
 * ★ 双链路（兼顾"能用"与"扫码"）：
 *   A) 分享链接 + 提取码直连（推荐，无需登录）：
 *      用百度开放平台接口 / 自建解析，凭 share_id + fs_id + sign 换取 dlink；
 *      直链必须带 Referer=https://pan.baidu.com，否则 403。
 *   B) 扫码登录兜底（无开放平台 key 或私密资源时）：
 *      电视端弹二维码，用「百度网盘」App 扫码，cookie 缓存后免扫。
 *
 * 说明：百度对 TV 端扫码登录限制较严，社区源普遍以"手动填 cookie / 开放平台"
 *       为主；本规则两种都实现，按可用性自动降级。
 *
 * 参考：FongMi/CatVodSpider · pan/baidu.js (MIT, 适配重写)
 */

(function (global) {
    'use strict';

    var UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';

    var Baidu = Object.create(Spider.BaseSpider);
    Baidu.siteKey  = 'baidu';
    Baidu.siteName = '百度网盘';
    Baidu.flag = 'baidu';

    function hd(cookie) {
        var h = { 'User-Agent': UA, 'Referer': 'https://pan.baidu.com', 'Origin': 'https://pan.baidu.com' };
        if (cookie) h['Cookie'] = cookie;
        return h;
    }

    function getApiKey() {
        var cfg = Spider.getConfig();
        return (cfg.baidu && cfg.baidu.api_key) || '';
    }

    // ============================================================
    // ① 扫码登录（链路 B）
    // ============================================================
    Baidu.getQrCodeToken = function () {
        try {
            // 百度 passport 扫码接口（与官方网页登录同源）
            var res = Spider.postJson('https://passport.baidu.com/v2/api/getqrcode', { t: Date.now() }, hd());
            var json = res ? JSON.parse(res) : null;
            var data = json && (json.data || json);
            if (!data || !data.imgurl) return null;
            return { qr: data.imgurl, token: data.sign || data.token || '' };
        } catch (e) { return null; }
    };

    Baidu.checkLoginStatus = function (token) {
        try {
            var res = Spider.postJson('https://passport.baidu.com/v2/api/checkqrcode', { token: token, t: Date.now() }, hd());
            var json = res ? JSON.parse(res) : null;
            var st = json && (json.status !== undefined ? json.status : (json.code === 0 ? 2 : 0));
            if (st === 2 || json.result) {
                // 扫码成功：百度返回 BDUSS cookie
                var d = json.data || json.result || json;
                var ck = d.cookie || d.BDUSS || (json.cookies && json.cookies.join(';')) || '';
                return { cookie: ck, ok: true };
            }
            return { ok: false, status: st };
        } catch (e) { return { ok: false }; }
    };

    // ============================================================
    // ② 分享信息解析（链路 A：提取码直连）
    //    id 形如：https://pan.baidu.com/s/xxxx  或  shareId
    // ============================================================
    function parseShare(shareUrl, pwd) {
        var cookie = Baidu.getCookie();
        var apiKey = getApiKey();
        try {
            // 优先：开放平台接口（需 api_key），稳定直连
            if (apiKey) {
                var body = { share_url: shareUrl, pwd: pwd || '', api_key: apiKey, limit: 200 };
                var res = Spider.postJson('https://pan.baidu.com/rest/2.0/xpan/share', body, hd(cookie));
                var json = res ? JSON.parse(res) : null;
                var items = (json && (json.list || (json.data && json.data.list))) || [];
                return items.map(function (it) {
                    return { vod_id: it.fs_id || it.path, vod_name: it.server_filename || it.name, vod_pic: '', vod_remarks: it.isdir ? '文件夹' : '' };
                });
            }
            // 兜底：通用分享列表（依赖 cookie，私密资源扫码后可用）
            var r2 = Spider.postJson('https://pan.baidu.com/share/list', { share_url: shareUrl, pwd: pwd || '' }, hd(cookie));
            var j2 = r2 ? JSON.parse(r2) : null;
            var list = (j2 && (j2.list || (j2.data && j2.data.list))) || [];
            return list.map(function (it) {
                return { vod_id: it.fs_id || it.path, vod_name: it.server_filename || it.name, vod_pic: '', vod_remarks: it.isdir ? '文件夹' : '' };
            });
        } catch (e) { return []; }
    }

    /** 换取下载直链（需 Referer + 可选 sign） */
    function getDownUrl(shareUrl, fileId, pwd) {
        var cookie = Baidu.getCookie();
        try {
            var body = { share_url: shareUrl, file_id: fileId, pwd: pwd || '' };
            var res = Spider.postJson('https://pan.baidu.com/rest/2.0/xpan/multimedia', body, hd(cookie));
            var json = res ? JSON.parse(res) : null;
            var dlink = (json && (json.dlink || (json.data && json.data.dlink))) || '';
            return dlink;
        } catch (e) { return ''; }
    }

    // ============================================================
    // 播放入口
    // ============================================================
    Baidu.playerContent = function (flag, id) {
        Spider.Log.info('百度网盘 playerContent id=' + id);
        var cookie = Baidu.getCookie();
        var apiKey = getApiKey();

        // 链路 A：有 api_key 或 cookie → 直连（不弹码）
        if (apiKey || cookie) {
            var url = getDownUrl(id, id, '');
            if (url) {
                return JSON.stringify({
                    url: url,
                    header: 'User-Agent: ' + UA + '\nReferer: https://pan.baidu.com\nOrigin: https://pan.baidu.com',
                    type: 18
                });
            }
        }
        // 链路 B：无鉴权 → 走扫码（电视端弹码，百度网盘 App 扫码）
        var qr = Baidu.getQrCodeToken();
        if (qr && qr.qr) {
            return JSON.stringify(Spider.authQr(qr.qr, qr.token, { flag: 'baidu', site: '百度网盘' }));
        }
        // 最终兜底：匿名尝试（公开分享或可播）
        return JSON.stringify({ url: id, header: 'User-Agent: ' + UA + '\nReferer: https://pan.baidu.com', type: 18 });
    };

    Baidu.searchContent = function (key) {
        if (/https?:\/\//.test(key)) return JSON.stringify({ list: parseShare(key, '') });
        return JSON.stringify({ list: [] });
    };
    Baidu.detailContent = function (ids) {
        var id = (ids && ids[0]) || '';
        if (/https?:\/\//.test(id)) return JSON.stringify({ list: parseShare(id, '') });
        return JSON.stringify({ list: [] });
    };

    Spider.register(Baidu);

})(this);
