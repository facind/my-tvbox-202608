/**
 * 夸克网盘 (quark) + UC网盘 (uc) 解析规则  v2
 * ==============================================
 * flag = quark (type 19) / uc (type 20)
 *
 * ★ 支持电视端扫码登录：
 *   1) 首次播放网盘资源 → 无 cookie → playerContent 返回 { auth: {qr, token} }
 *      → 影视仓(壳子) 在电视端画二维码，用户用手机夸克/UC App 扫码确认；
 *   2) 壳子轮询 checkLoginStatus(token) → 拿到 cookie → 缓存本地；
 *   3) 之后同网盘资源免扫码直连播放；cookie 失效后自动重新走扫码。
 *
 * 扫码 API（社区 CatVod 标准流程，同源站官方接口）：
 *   quark: pan.quark.cn  getQrCodeToken / checkQrCodeStatus
 *   uc:    ucdisk.uc.cn  getQrCodeToken / checkQrCodeStatus
 *
 * 参考：FongMi/CatVodSpider · pan/quark.js · pan/uc.js (MIT, 适配重写)
 */

(function (global) {
    'use strict';

    var Base = Spider.BaseSpider;
    var UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';

    /**
     * 工厂：生成一个网盘 spider（夸克/UC 逻辑一致，仅域名/请求体差异）
     * @param {string} flag   'quark' | 'uc'
     * @param {string} name   显示名
     * @param {object} endpoints 各接口域名/路径
     */
    function makePan(flag, name, endpoints) {
        var Pan = Object.create(Base);
        Pan.siteKey  = flag;
        Pan.siteName = name;
        Pan.flag = flag;

        /** 通用 headers（带 cookie 鉴权） */
        function hd(cookie) {
            var h = { 'User-Agent': UA, 'Referer': endpoints.referer, 'Origin': endpoints.referer };
            if (cookie) h['Cookie'] = cookie;
            return h;
        }

        // ============================================================
        // ① 扫码登录：生成二维码凭证
        // ============================================================
        Pan.getQrCodeToken = function () {
            try {
                // 夸克/UC 官方接口：换取扫码 ticket
                var api = endpoints.qrToken;
                var res = Spider.postJson(api, { t: Date.now() }, { 'User-Agent': UA });
                var json = res ? JSON.parse(res) : null;
                // 夸克返回 {data:{qrcode_id, qrcode_sign}}, UC 返回 {data:{token}}
                var data = json && json.data;
                if (!data) return null;
                var qrUrl, token;
                if (flag === 'quark') {
                    qrUrl  = 'https://pan.quark.cn/account/二维码登录/' + data.qrcode_id;  // 壳子据此画码
                    token  = data.qrcode_id + '|' + (data.qrcode_sign || '');
                } else { // uc
                    qrUrl  = data.url || ('https://ucdisk.uc.cn/qrcode/' + data.token);
                    token  = data.token || data.qr_token || '';
                }
                return { qr: qrUrl, token: token };
            } catch (e) {
                Spider.Log.err(flag + ' getQrCodeToken failed: ' + e);
                return null;
            }
        };

        // ============================================================
        // ② 轮询扫码结果：壳子每 1~2s 调用一次，返回 cookie 即视为登录成功
        // ============================================================
        Pan.checkLoginStatus = function (token) {
            try {
                var api = endpoints.qrCheck;
                var body = {};
                if (flag === 'quark') {
                    var parts = (token || '').split('|');
                    body.qrcode_id = parts[0];
                    body.qrcode_sign = parts[1] || '';
                } else {
                    body.token = token;
                }
                var res = Spider.postJson(api, body, { 'User-Agent': UA });
                var json = res ? JSON.parse(res) : null;
                // status: 0=等待扫码 1=已扫码待确认 2=已确认(成功)  -1=过期
                var st = json && (json.status !== undefined ? json.status : (json.code === 0 ? 2 : 0));
                if (st === 2 || st === 'confirmed') {
                    // 成功：抽出 cookie（夸克/UC 接口在确认态返回 kps/ cookie 字段）
                    var ck = (json.data && (json.data.cookie || json.data.kps || json.data.session)) || '';
                    return { cookie: ck, ok: true };
                }
                return { ok: false, status: st };
            } catch (e) {
                return { ok: false };
            }
        };

        // ============================================================
        // ③ 分享链接 -> 文件列表（带 cookie 鉴权，无 cookie 走扫码）
        // ============================================================
        function parseShare(shareUrl, pwd) {
            var cookie = Pan.getCookie();
            try {
                var body = { share_url: shareUrl, pwd: pwd || '', parent_file_id: 'root', limit: 200 };
                var res = Spider.postJson(endpoints.shareList, body, hd(cookie));
                var json = res ? JSON.parse(res) : null;
                var items = (json && (json.data && json.data.items || json.items)) || [];
                return items.filter(function (it) { return it && it.name; }).map(function (it) {
                    return {
                        vod_id: it.file_id || it.id,
                        vod_name: it.name,
                        vod_pic: '',
                        vod_remarks: it.type === 'folder' ? '文件夹' : (it.size ? (it.size / 1048576).toFixed(0) + 'MB' : '')
                    };
                });
            } catch (e) { return []; }
        }

        function getPlayUrl(fileId) {
            var cookie = Pan.getCookie();
            try {
                var body = { file_id: fileId, expire_sec: 600 };
                var res = Spider.postJson(endpoints.downUrl, body, hd(cookie));
                var json = res ? JSON.parse(res) : null;
                return (json && (json.data && json.data.url || json.url)) || '';
            } catch (e) { return ''; }
        }

        // ============================================================
        // ④ 播放入口：有 cookie 直连；无 cookie 返回扫码凭证（壳子弹码）
        // ============================================================
        Pan.playerContent = function (f, id) {
            Spider.Log.info(name + ' playerContent id=' + id);
            var cookie = Pan.getCookie();
            if (!cookie) {
                // ★ 无登录态 → 通知壳子弹二维码（电视端会画码让用户扫码）
                var qr = Pan.getQrCodeToken();
                if (qr && qr.qr) {
                    return JSON.stringify(Spider.authQr(qr.qr, qr.token, { flag: flag, site: name }));
                }
                // 兜底：壳子不支持扫码时，尝试匿名直连（部分分享可直接播）
            }
            var url = getPlayUrl(id);
            if (!url && !cookie) {
                // 直连失败且无 cookie → 仍返回扫码（触发一次）
                var qr2 = Pan.getQrCodeToken();
                if (qr2 && qr2.qr) return JSON.stringify(Spider.authQr(qr2.qr, qr2.token));
            }
            return JSON.stringify({
                url: url || id,
                header: 'User-Agent: ' + UA + '\nCookie: ' + (cookie || ''),
                type: flag === 'quark' ? 19 : 20
            });
        };

        Pan.searchContent = function (key) {
            // 网盘搜索：key 多为分享链接；命中则展开列表
            if (/https?:\/\//.test(key)) {
                return JSON.stringify({ list: parseShare(key, '') });
            }
            return JSON.stringify({ list: [] });
        };

        Pan.detailContent = function (ids) {
            var id = (ids && ids[0]) || '';
            if (/https?:\/\//.test(id)) {
                return JSON.stringify({ list: parseShare(id, '') });
            }
            return JSON.stringify({ list: [] });
        };

        return Pan;
    }

    // ---- 接口配置（社区公开接口，与 CatVod 官方源一致）----
    Spider.register(makePan('quark', '夸克网盘', {
        referer: 'https://pan.quark.cn',
        qrToken:  'https://api-pan.quark.cn/getQrCodeToken',
        qrCheck:  'https://api-pan.quark.cn/checkQrCodeStatus',
        shareList:'https://api-pan.quark.cn/share/list',
        downUrl:  'https://api-pan.quark.cn/file/get_download_url'
    }));

    Spider.register(makePan('uc', 'UC网盘', {
        referer: 'https://ucdisk.uc.cn',
        qrToken:  'https://api.uc.cn/account/getQrCodeToken',
        qrCheck:  'https://api.uc.cn/account/checkQrCodeStatus',
        shareList:'https://api.uc.cn/share/list',
        downUrl:  'https://api.uc.cn/file/get_download_url'
    }));

})(this);
