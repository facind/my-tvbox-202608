/**
 * 本地验证：模拟 Java 宿主注入，用 node / GraalJS 跑通四网盘规则
 * 用法：node test_spider.js
 */
(function () {
    'use strict';

    var callLog = [];
    function makeResp(obj) { return JSON.stringify(obj); }

    /**
     * 模拟宿主注入的全局（对应 Spider.java 里的 putMember）
     * - __fetch__(url, headersJson)
     * - __post__(url, body, headersJson)   // 三参数，与 JS 侧 postJson 对齐
     * - __config__()
     * - __store__(k,v) / __load__(k)
     */
    var store = {};
    // ---- polyfill：GraalJS 全局（生产环境自带，node 测试补齐）----
    if (typeof print !== 'function') global.print = function () { console.log(Array.prototype.join.call(arguments, ' ')); };
    if (typeof load !== 'function') global.load = function (file) {
        var code = fs.readFileSync(require('path').join(__dirname, file), 'utf8');
        vm.runInContext(code, global, { filename: file });
    };

    global.__fetch__ = function (url, headersJson) {
        callLog.push(['GET', url]);
        return makeResp({});
    };
    global.__post__ = function (url, body, headersJson) {
        callLog.push(['POST', url, body]);
        // ---- 阿里云盘 ----
        if (/token\/refresh/.test(url))  return makeResp({ access_token: 'ALI_AT', refresh_token: 'ALI_RT_NEW' });
        if (/get_download_url/.test(url)) return makeResp({ url: 'https://ali.cdn/play.mp4', size: 50 * 1024 * 1024, template_id: '720p' });
        if (/users\/qrcode\/get/.test(url)) return makeResp({ data: { qrCodeUrl: 'https://api.aliyundrive.com/qr/SCAN_ALI', t: 'ALI_TOKEN' } });
        if (/users\/qrcode\/check/.test(url)) return makeResp({ status: 2, data: { refresh_token: 'ALI_RT_FROM_QR' } });
        if (/list_by_share_url/.test(url)) return makeResp({ items: [{ file_id: 'ali_001', name: '电影.mp4', type: 'file', size: 50 * 1024 * 1024 }] });
        // ---- 夸克/UC（工厂，共用路径，按 url 区分）----
        if (/api-pan\.quark\.cn\/getQrCodeToken/.test(url)) return makeResp({ data: { qrcode_id: 'QID', qrcode_sign: 'QSIGN' } });
        if (/api-pan\.quark\.cn\/checkQrCodeStatus/.test(url)) return makeResp({ status: 2, data: { kps: 'QUARK_KPS' } });
        if (/api\.uc\.cn\/account\/getQrCodeToken/.test(url)) return makeResp({ data: { token: 'UC_TOKEN', url: 'https://uc/qr/UC_QR' } });
        if (/api\.uc\.cn\/account\/checkQrCodeStatus/.test(url)) return makeResp({ status: 2, data: { cookie: 'UC_COOKIE' } });
        // ---- 百度 ----
        if (/passport\.baidu\.com\/v2\/api\/getqrcode/.test(url)) return makeResp({ data: { imgurl: 'https://passport.baidu.com/qr/BD_SCAN', sign: 'BD_SIGN' } });
        if (/passport\.baidu\.com\/v2\/api\/checkqrcode/.test(url)) return makeResp({ status: 2, data: { BDUSS: 'BD_BDUSS', cookie: 'BD_COOKIE' } });
        // ---- 分享列表 ----
        if (/share\/list/.test(url))       return makeResp({ list: [{ fs_id: 'bd_001', server_filename: '剧集.mkv' }] });
        if (/xpan\/multimedia/.test(url))  return makeResp({ dlink: 'https://baidu.cdn/play.mkv' });
        return makeResp({});
    };
    global.__config__ = function () {
        return JSON.stringify({
            aliyun: { refresh_token: 'TEST_ALI_RT' },   // ★ 有 refresh_token → 阿里应直连不扫码
            baidu:  { api_key: 'TEST_BD_KEY' }          // ★ 有 api_key → 百度应直连不扫码
        });
    };
    global.__store__ = function (k, v) { store[k] = v; };  // v 已是 JSON.stringify 后的字符串
    global.__load__  = function (k) { return (k in store) ? store[k] : null; };

    // 加载适配层 + 四网盘规则（顺序与 Spider.java 一致）
    // 用 global 本身作为 vm context，使 IIFE 内 this === global，Spider/print 等互通
    var fs = require('fs');
    var vm = require('vm');
    var ctx = vm.createContext(global);
    function load(file) {
        var code = fs.readFileSync(require('path').join(__dirname, file), 'utf8');
        vm.runInContext(code, global, { filename: file });
    }
    load('js/spider.js');
    load('js/pan_aliyun.js');
    load('js/pan_baidu.js');
    load('js/pan_quark_uc.js');

    var ok = 0, fail = 0;
    function assert(name, cond) {
        if (cond) { ok++; console.log('  ✅ ' + name); }
        else { fail++; console.log('  ❌ ' + name); }
    }

    console.log('\n[1] 注册检查');
    assert('注册了 aliyun/baidu/quark/uc', Spider.all().length === 4);
    assert('get(quark) 命中 flag=quark', Spider.get('quark').flag === 'quark');
    assert('get(baidu) 命中 flag=baidu', Spider.get('baidu').flag === 'baidu');
    assert('get 未知 -> BaseSpider（type=24 兜底）', Spider.get('xxx').playerContent('xxx', 'id').indexOf('"type":24') > 0);

    console.log('\n[2] flag -> type 路由（走 BaseSpider 纯路由，验证 flag->type 映射）');
    function route(f) { return JSON.parse(Spider.BaseSpider.playerContent(f, 'id')).type; }
    assert('baidu -> type 18', route('baidu') === 18);
    assert('quark -> type 19', route('quark') === 19);
    assert('uc    -> type 20', route('uc') === 20);
    assert('aliyun-> type 21', route('aliyun') === 21);
    assert('未知  -> type 24', route('xxx') === 24);

    console.log('\n[3] 阿里云盘：有 refresh_token → 直连不扫码 + >40MiB 转码');
    var ali = JSON.parse(Spider.get('aliyun').playerContent('aliyun', 'file_id_xyz'));
    assert('阿里返回直链', /ali.cdn\/play.mp4/.test(ali.url));
    assert('>40MiB 自动拼 template_id', /template_id=720p/.test(ali.url));
    assert('阿里无扫码（已配 refresh_token）', !ali.auth);

    console.log('\n[4] 百度：有 api_key → 直连不扫码');
    var bd = JSON.parse(Spider.get('baidu').playerContent('baidu', 'https://pan.baidu.com/s/xxx'));
    assert('百度带 Referer 鉴权', /Referer: https:\/\/pan.baidu.com/.test(bd.header));
    assert('百度无扫码（已配 api_key）', !bd.auth);

    console.log('\n[5] 扫码契约（清空 config/store，模拟首次无登录态）');
    global.__config__ = function () { return JSON.stringify({}); };
    Object.keys(store).forEach(function (k) { delete store[k]; });  // 清空缓存（保留引用，闭包不失效）
    var qr = JSON.parse(Spider.getQrCodeToken('quark'));
    assert('quark getQrCodeToken 返回 qr+token', qr && qr.qr && qr.token);
    assert('uc 同样支持扫码', (function () { var q = JSON.parse(Spider.getQrCodeToken('uc')); return q && q.qr; })());
    var bdQr = JSON.parse(Spider.getQrCodeToken('baidu'));
    console.log('   [dbg] baidu qr raw =', JSON.stringify(bdQr));
    assert('baidu 支持扫码', bdQr && bdQr.qr);
    var aliQr = JSON.parse(Spider.getQrCodeToken('aliyun'));
    console.log('   [dbg] aliyun qr raw =', JSON.stringify(aliQr));
    assert('aliyun 支持扫码兜底', aliQr && aliQr.qr);

    console.log('\n[6] 模拟"用户扫码确认" → 缓存 cookie → 后续免扫');
    var st = JSON.parse(Spider.checkLoginStatus('quark', 'QID|QSIGN'));
    assert('夸克扫码确认 -> 返回 cookie', st && st.cookie);
    console.log('   [dbg] store keys after check =', Object.keys(store), 'quark_cookie=', JSON.stringify(store['quark_cookie']));
    assert('夸克 cookie 已本地缓存', JSON.parse(store['quark_cookie']) === 'QUARK_KPS');
    // 扫码后再次播放 → 有 cookie → 直连（不弹码），验证"免扫"
    var qplay = JSON.parse(Spider.get('quark').playerContent('quark', 'file_001'));
    assert('扫码后免扫直连（无 auth 字段）', !qplay.auth);

    console.log('\n[7] searchContent 识别分享链接 -> 文件列表');
    var s = JSON.parse(Spider.get('aliyun').searchContent('https://www.aliyundrive.com/s/abc', false));
    console.log('   [dbg] aliyun search list =', JSON.stringify(s.list));
    assert('阿里搜索返回文件列表', s.list && s.list.length > 0 && s.list[0].vod_name === '电影.mp4');

    console.log('\n[8] BaseSpider 兜底');
    var base = Spider.get('notexist').playerContent('notexist', 'id');
    assert('未知 flag 降级 type=24', JSON.parse(base).type === 24);

    console.log('\n==== 结果 ====');
    console.log('通过: ' + ok + '  失败: ' + fail);
    process.exit(fail > 0 ? 1 : 0);
})();
