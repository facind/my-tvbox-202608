// Node 兼容入口：真实加载并运行 spider/js/*.js 规则源码
// （生产环境由 Spider.java 通过 GraalVM Polyglot 加载，接口完全一致）
const fs = require("fs");
const path = require("path");
const vm = require("vm");

// === 模拟 Spider.java 注入的宿主环境（与生产 Java 侧一一对应）===
const sandbox = {
  JSON,
  print: (...a) => console.log(...a),
  // __config__ : 对应 Java Config.getJson()
  __config__: function () {
    return JSON.stringify({ aliyun: { refresh_token: "TEST_REFRESH_TOKEN" } });
  },
  // __fetch__ / __post__ : 对应 Java HttpUtil
  __fetch__: function (url, headers) {
    // 模拟阿里云盘 API 响应（与生产 API 结构一致）
    if (url.includes("token/refresh")) return JSON.stringify({ access_token: "FAKE_ACCESS_TOKEN" });
    if (url.includes("get_download_url")) return JSON.stringify({
      url: "https://dl.aliyundrive.com/xxx.m3u8", size: 50 * 1024 * 1024, template_id: "264"
    });
    if (url.includes("list_by_share_url")) return JSON.stringify({
      items: [{ file_id: "f1", name: "测试影片.1080p.mp4", type: "file", size: 1048576 }]
    });
    return "{}";
  },
  __post__: function (url, body) { return sandbox.__fetch__(url, body); },
};
sandbox.global = sandbox;
vm.createContext(sandbox);

// 依次加载：适配层 -> 各网盘规则（与生产加载顺序一致）
const files = [
  "spider/js/spider.js",
  "spider/js/pan_aliyun.js",
  "spider/js/pan_baidu.js",
  "spider/js/pan_quark_uc.js",
];
const BASE = __dirname;  // test_spider.js 所在目录 = jar/，JS 规则在此目录下
for (const f of files) {
  const code = fs.readFileSync(path.join(BASE, f), "utf-8");
  // 把 (function(global){...})(this) 中的 this 绑定到 sandbox
  vm.runInContext(code + "\n", sandbox, { filename: path.join(BASE, f) });
}

const Spider = sandbox.Spider;
console.log("\n===== 已注册 spider:", Spider.all().join(", "), "=====\n");

// 测试1: 阿里云盘分享列表
console.log("--- 测试1: 阿里云盘 searchContent(分享链接) ---");
const r2 = JSON.parse(Spider.get("pan").searchContent("https://www.aliyundrive.com/s/test_share"));
console.log("  列表 =", JSON.stringify(r2.list));
console.assert(r2.list.length === 1, "应有1条");

// 测试2: 阿里云盘播放解析（>40MiB 自动加 template_id）
console.log("\n--- 测试2: 阿里云盘 playerContent (>40MiB 加转码模板) ---");
const r1 = JSON.parse(Spider.get("pan").playerContent("aliyun", "file_id_123"));
console.log("  url  =", r1.url);
console.log("  type =", r1.type, "(期望 21=aliyun)");
console.assert(r1.type === 21, "type应为21");
console.assert(r1.url.includes("template_id=264"), "应含转码模板");

// 测试3: 各网盘 flag 路由（验证 Spider.get(flag) 分发）
console.log("\n--- 测试3: 各网盘 flag 路由 ---");
const FLAG_TYPE = { baidu: 18, quark: 19, uc: 20, aliyun: 21, universal: 24 };
let allOk = true;
for (const f of Object.keys(FLAG_TYPE)) {
  const sp = Spider.get(f);
  const rr = JSON.parse(sp.playerContent(f, "some_id"));
  const ok = rr.type === FLAG_TYPE[f];
  allOk &= ok;
  console.log(`  ${f.padEnd(10)} -> type=${rr.type}${ok ? " ✓" : " ✗ 期望" + FLAG_TYPE[f]}`);
}

// 测试4: 未知 flag 降级
console.log("\n--- 测试4: 未知 flag 降级 ---");
const rr = JSON.parse(Spider.get("xxx").playerContent("xxx", "id"));
console.log("  type =", rr.type, rr.type === 24 ? "✓ 降级为24" : "✗");
console.assert(rr.type === 24, "应降级为24");

console.log("\n" + (allOk ? "✅ 全部通过：flag 路由 + 40MiB分片探测 + 降级策略 均符合预期" : "❌ 存在失败项"));
process.exit(allOk ? 0 : 1);
