package spider;

import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/**
 * 影视仓 / TVBox 自定义 Spider · 宿主入口
 * ==========================================
 * 1) 提供 HTTP GET/POST（供 JS 规则通过 __fetch__/__post__ 调用）
 * 2) 读取配置（refresh_token 等，供网盘规则鉴权）
 * 3) 网盘 flag 降级解析（JS 规则未加载时的兜底实现）
 *
 * 影视仓加载 spider.jar 后，按标准接口反射调用：
 *   searchContent / detailContent / playerContent ...
 *
 * 网盘 flag 映射：baidu=18  quark=19  uc=20  aliyun=21  universal=24
 */
public class Main {

    private static final String UA = "Mozilla/5.0 (Linux; Android 11; TVBox) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0 Safari/537.36";
    private static JSONObject configCache;

    // =========================================================
    // HTTP 工具（供 Spider.java / JS 规则调用）
    // =========================================================
    static String httpGet(String url, String headersJson) {
        return request("GET", url, null, headersJson);
    }

    static String httpPost(String url, String body) {
        return request("POST", url, body, "{}");
    }

    /** JS postJson(url, body, headers) 使用：body + headers 独立 */
    static String httpPostWithHeaders(String url, String body, String headersJson) {
        return request("POST", url, body, headersJson == null ? "{}" : headersJson);
    }

    private static String request(String method, String url, String body, String headersJson) {
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
            c.setRequestMethod(method);
            c.setConnectTimeout(15000);
            c.setReadTimeout(15000);
            c.setRequestProperty("User-Agent", UA);

            // 解析 headers json
            JSONObject hj = new JSONObject(headersJson == null ? "{}" : headersJson);
            for (String k : hj.keySet()) c.setRequestProperty(k, hj.getString(k));

            if (body != null && !body.isEmpty()) {
                c.setDoOutput(true);
                try (OutputStream os = c.getOutputStream()) {
                    os.write(body.getBytes(StandardCharsets.UTF_8));
                }
            }
            int code = c.getResponseCode();
            InputStream is = (code >= 400 && code < 600) ? c.getErrorStream() : c.getInputStream();
            if (is == null) return "";
            try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
                StringBuilder sb = new StringBuilder();
                String line;
                while ((line = br.readLine()) != null) sb.append(line);
                return sb.toString();
            }
        } catch (Exception e) {
            return "";
        }
    }

    // =========================================================
    // 配置读取（优先环境变量 > 同级 config.json > 内置空配置）
    // =========================================================
    static String getConfigJson() {
        if (configCache != null) return configCache.toString();
        JSONObject cfg = new JSONObject();
        try {
            // 1) 环境变量（推荐，CI/容器友好）
            Map<String, String> env = System.getenv();
            if (env.containsKey("ALIYUN_REFRESH_TOKEN")) {
                cfg.put("aliyun", new JSONObject().put("refresh_token", env.get("ALIYUN_REFRESH_TOKEN")));
            }
            // 2) 同级 config.json
            InputStream in = Main.class.getClassLoader().getResourceAsStream("config.json");
            if (in != null) {
                JSONObject fileCfg = new JSONObject(new String(in.readAllBytes(), StandardCharsets.UTF_8));
                for (String k : fileCfg.keySet()) cfg.put(k, fileCfg.get(k));
            }
        } catch (Exception ignored) {}
        configCache = cfg;
        return cfg.toString();
    }

    // =========================================================
    // 影视仓标准接口（type=3 单仓调用）
    // =========================================================
    public static Object homeContent(boolean filter)       { return new JSONObject().toString(); }
    public static Object homeVideoContent()                { return new JSONObject().toString(); }
    public static Object categoryContent(String tid, String pg, boolean f, HashMap<String,String> e) { return new JSONObject().toString(); }
    public static Object searchContent(String key, boolean quick) {
        return new JSONObject().put("list", new org.json.JSONArray()).toString();
    }
    public static Object detailContent(String[] ids)       { return new JSONObject().toString(); }

    /** ★ 播放解析：网盘按 flag 分流（JS 规则未加载时的 Java 降级实现） */
    public static Object playerContent(String flag, String id, String vipFlags) {
        return parse(flag, id);
    }
    public static Object playerContent(String flag, String id) { return parse(flag, id); }

    private static final Map<String, Integer> FLAG_TYPE = new HashMap<>();
    static { FLAG_TYPE.put("baidu", 18); FLAG_TYPE.put("quark", 19); FLAG_TYPE.put("uc", 20); FLAG_TYPE.put("aliyun", 21); FLAG_TYPE.put("universal", 24); }

    public static Object parse(String flag, String url) {
        JSONObject jo = new JSONObject();
        jo.put("url", url);
        jo.put("header", "User-Agent: " + UA);
        jo.put("type", FLAG_TYPE.getOrDefault(flag, 24));
        return jo.toString();
    }

    // 采集类兼容
    public static void init(Object... args) {}

    // 本地自测
    public static void main(String[] args) {
        System.out.println("flag=baidu  -> " + parse("baidu",  "https://pan.baidu.com/s/xxx"));
        System.out.println("flag=quark  -> " + parse("quark",  "https://pan.quark.cn/s/xxx"));
        System.out.println("flag=uc     -> " + parse("uc",     "https://www.uc.cn/s/xxx"));
        System.out.println("flag=aliyun -> " + parse("aliyun", "https://www.aliyundrive.com/s/xxx"));
        System.out.println("config: " + getConfigJson());
    }
}
