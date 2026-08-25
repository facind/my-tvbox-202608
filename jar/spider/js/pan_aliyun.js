/**
 * 阿里云盘 (aliyun) 解析规则  v2
 * ==================================
 * flag = aliyun  (type 21)
 *
 * ★ 双模式鉴权（推荐优先 refresh_token，免扫码）：
 *   A) 已配置 refresh_token（config 里）→ 直接换 access_token → 直链播放，不弹码；
 *   B) 未配置 → 走扫码登录（getQrCodeToken / checkLoginStatus），
 *      电视端弹二维码，用「阿里云盘」App 扫码，首次扫后缓存，后续免扫。
 *
 * 分享链接 -> 文件列表 -> 直链播放；单文件 > 40MiB 自动拼转码模板。
 *
 * 参考：FongMi/CatVodSpider · pan/aliyun.js (MIT, 简化适配版)
 */

(function (global) {
    'use strict';

    var API_LIST  = 'https://api.aliyundrive.com/adrive/v2/file/list_by_share_url';
    var API_GET   = 'https://api.aliyundrive.com/v2/file/get_by_path';
    var API_DOWN  = 'https://api.aliyundrive.com/v2/file/get_download_url';
    var API_REFRESH = 'https://api.aliyundrive.com/token/refresh';
    var API_QR_TOKEN = 'https://api.aliyundrive.com/users/qrcode/get';
    var API_QR_CHECK = 'https://api.aliyundrive.com/users/qrcode/check';

    var UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';

    var Aliyun = Object.create(Spider.BaseSpider);
    Aliyun.siteKey  = 'aliyun';
    Aliyun.siteName = '阿里云盘';
    Aliyun.flag = 'aliyun';

    function hd(token) {
        var h = { 'User-Agent': UA, 'Referer': 'https://www.aliyundrive.com/', 'Origin': 'https://www.aliyundrive.com/' };
        if (token) h['Authorization'] = 'Bearer ' + token;
        return h;
    }

    /** 读 refresh_token（config 优先，其次本地缓存） */
    function getRefreshToken() {
        var cfg = Spider.getConfig();
        return (cfg.aliyun && cfg.aliyun.refresh_token) || Aliyun.getCookie('rt') || '';
    }

    /** ① refresh_token -> access_token */
    function getAccessToken() {
        var rt = getRefreshToken();
        if (!rt) return '';
        try {
            var res = Spider.postJson(API_REFRESH, { refresh_token: rt }, hd());
            var json = res ? JSON.parse(res) : null;
            var at = json && (json.access_token || (json.data && json.data.access_token)) || '';
            if (at && json && json.refresh_token) Aliyun.setCookie('rt', json.refresh_token); // 刷新后更新
            return at;
        } catch (e) { return ''; }
    }

    // ============================================================
    // ★ 扫码登录（模式 B：未配 refresh_token 时）
    // ============================================================
    Aliyun.getQrCodeToken = function () {
        try {
            var res = Spider.postJson(API_QR_TOKEN, { device: 'TVBox' }, hd());
            var json = res ? JSON.parse(res) : null;
            var data = json && (json.data || json);
            if (!data || !data.qrCodeUrl) return null;
            return { qr: data.qrCodeUrl, token: data.t || data.qrcodeKey || data.token || '' };
        } catch (e) { return null; }
    };

    Aliyun.checkLoginStatus = function (token) {
        try {
            var res = Spider.postJson(API_QR_CHECK, { t: token }, hd());
            var json = res ? JSON.parse(res) : null;
            var st = json && (json.status !== undefined ? json.status : (json.code === 0 ? 2 : 0));
            if (st === 2 || json.result) {
                // 扫码成功：阿里返回 refresh_token / access_token
                var d = json.data || json.result || json;
                var rt = d.refresh_token || d.refreshToken || '';
                if (rt) Aliyun.setCookie('rt', rt); // 缓存，之后走模式 A 免扫码
                return { cookie: rt, ok: true };
            }
            return { ok: false, status: st };
        } catch (e) { return { ok: false }; }
    };

    // ============================================================
    // 分享链接 -> 文件列表
    // ============================================================
    function listByShare(shareUrl, pwd) {
        var token = getAccessToken();
        var body = { share_url: shareUrl, parent_file_id: 'root', limit: 200 };
        if (pwd) body.share_pwd = pwd;
        try {
            var res = Spider.postJson(API_LIST, body, hd(token));
            var json = res ? JSON.parse(res) : null;
            var items = (json && (json.items || (json.data && json.data.items))) || [];
            return items.map(function (it) {
                return {
                    vod_id: it.file_id,
                    vod_name: it.name,
                    vod_pic: '',
                    vod_remarks: it.type === 'folder' ? '文件夹' : (it.size ? (it.size / 1048576).toFixed(0) + 'MB' : '')
                };
            });
        } catch (e) { return []; }
    }

    /** >40MiB 自动拼转码模板 */
    function getPlayUrl(fileId) {
        var token = getAccessToken();
        try {
            var res = Spider.postJson(API_DOWN, { file_id: fileId, expire_sec: 600 }, hd(token));
            var json = res ? JSON.parse(res) : null;
            var url = (json && (json.url || (json.data && json.data.url))) || '';
            var size = (json && (json.size || (json.data && json.data.size))) || 0;
            var tpl  = (json && (json.template_id || (json.data && json.data.template_id))) || '';
            if (size > 40 * 1024 * 1024 && tpl) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'template_id=' + tpl;
            return url;
        } catch (e) { return ''; }
    }

    // ============================================================
    // 播放入口：有 token 直连；无则扫码
    // ============================================================
    Aliyun.playerContent = function (flag, id) {
        Spider.Log.info('阿里云盘 playerContent id=' + id);
        var token = getAccessToken();
        if (!token) {
            // 无 refresh_token → 走扫码（电视端弹码，扫一次后缓存 rt，后续免扫）
            var qr = Aliyun.getQrCodeToken();
            if (qr && qr.qr) return JSON.stringify(Spider.authQr(qr.qr, qr.token, { flag: 'aliyun', site: '阿里云盘' }));
        }
        var url = getPlayUrl(id);
        return JSON.stringify({
            url: url || id,
            header: 'User-Agent: ' + UA,
            type: 21
        });
    };

    Aliyun.searchContent = function (key) {
        if (/https?:\/\//.test(key)) return JSON.stringify({ list: listByShare(key, '') });
        return JSON.stringify({ list: [] });
    };
    Aliyun.detailContent = function (ids) {
        var id = (ids && ids[0]) || '';
        if (/https?:\/\//.test(id)) return JSON.stringify({ list: listByShare(id, '') });
        return JSON.stringify({ list: [] });
    };

    Spider.register(Aliyun);

})(this);
