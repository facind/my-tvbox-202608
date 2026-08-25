package spider;

import org.graalvm.polyglot.*;
import org.json.JSONObject;

import java.nio.file.*;
import java.util.HashMap;
import java.util.Map;

/**
 * 影视仓 / TVBox 自定义 Spider（网盘 + 采集 统一入口）
 * ======================================================
 * 通过 GraalVM Polyglot 加载 jar/spider/js/*.js 规则文件，
 * 影视仓按标准接口反射调用，实现热插拔的源站/网盘解析。
 *
 * 标准接口（影视仓 type=3 单仓调用）：
 *   homeContent / categoryContent / searchContent / detailContent / playerContent
 *
 * 网盘 flag 路由：baidu=18  quark=19  uc=20  aliyun=21  universal=24
 *
 * 编译打包：./build.sh  ->  spider.jar
 * 参考：FongMi/CatVodSpider (MIT) 的 JS 插件设计思想
 */
public class Spider {

    private static final String JS_DIR = "jar/spider/js/";

    // ---- JS 引擎（懒加载，GraalVM Polyglot）----
    private static volatile Context ctx;
    private static Context context() {
        if (ctx == null) {
            synchronized (Spider.class) {
                if (ctx == null) {
                    ctx = Context.newBuilder("js")
                            .allowHostAccess(HostAccess.ALL)
                            .allowHostClassLookup(s -> true)
                            .build();
                    loadScripts();
                }
            }
        }
        return ctx;
    }

    /** 加载所有 .js 规则，并注入 __fetch__ / __post__ / __config__ 宿主方法 */
    private static void loadScripts() {
        Context c = ctx;
        // 注入宿主：HTTP GET / POST / 配置读取
        c.getBindings("js").putMember("__fetch__", (java.util.function.BiFunction<String, String, String>)
                (url, headersJson) -> HttpUtil.get(url, headersJson));
        c.getBindings("js").putMember("__post__", (java.util.function.Function<Object[], String>)
                (args) -> {
                    String url = (String) args[0];
                    String body = args.length > 1 && args[1] != null ? (String) args[1] : "{}";
                    String headers = args.length > 2 && args[2] != null ? (String) args[2] : "{}";
                    return HttpUtil.post(url, body, headers);
                });
        c.getBindings("js").putMember("__config__", (java.util.function.Supplier<String>)
                Config::getJson);
        // ★ 本地持久化（扫码 cookie / refresh_token 缓存到 jar 同级 store/ 目录）
        c.getBindings("js").putMember("__store__", (java.util.function.BiConsumer<String, String>)
                (key, val) -> Store.put(key, val));
        c.getBindings("js").putMember("__load__", (java.util.function.Function<String, String>)
                Store::get);

        try {
            Path dir = Paths.get(Spider.class.getClassLoader()
                    .getResource(JS_DIR.replace("jar/", "")).toURI());
            Files.walk(dir).filter(p -> p.toString().endsWith(".js")).forEach(p -> {
                try {
                    c.eval("js", new String(Files.readAllBytes(p), "UTF-8"));
                } catch (Exception e) { /* log */ }
            });
        } catch (Exception e) {
            // 资源未找到时降级：规则未打包，仅用 Java 骨架
        }
    }

    // ---- 供 JS 规则调用的宿主工具 ----
    public static class HttpUtil {
        public static String get(String url, String headersJson) {
            return Main.httpGet(url, headersJson == null ? "{}" : headersJson);
        }
        public static String post(String url, String body) {
            return Main.httpPost(url, body);
        }
        /** JS 侧 postJson(url, body, headers) -> 委托 Main.httpPostWithHeaders */
        public static String post(String url, String body, String headersJson) {
            return Main.httpPostWithHeaders(url, body == null ? "{}" : body, headersJson == null ? "{}" : headersJson);
        }
    }

    /**
     * 扫码 cookie / refresh_token 本地持久化
     * 存储位置：jar 同级 store/<key>.json（TV 端可写目录）
     */
    public static class Store {
        private static final java.nio.file.Path DIR = resolveDir();
        private static java.nio.file.Path resolveDir() {
            try {
                String base = System.getProperty("spider.store", "store");
                java.nio.file.Path p = java.nio.file.Paths.get(base);
                try { java.nio.file.Files.createDirectories(p); } catch (Exception ignored) {}
                return p;
            } catch (Exception e) { return java.nio.file.Paths.get("store"); }
        }
        public static void put(String key, String val) {
            try { java.nio.file.Files.write(DIR.resolve(key + ".json"),
                    val.getBytes(java.nio.charset.StandardCharsets.UTF_8)); } catch (Exception ignored) {}
        }
        public static String get(String key) {
            try { return new String(java.nio.file.Files.readAllBytes(DIR.resolve(key + ".json")),
                    java.nio.charset.StandardCharsets.UTF_8); } catch (Exception e) { return null; }
        }
    }

    public static class Config {
        public static String getJson() {
            return Main.getConfigJson();
        }
    }

    // ---- 影视仓标准接口（反射调用入口）----

    public static Object homeContent(boolean filter) {
        return call("homeContent", filter ? "true" : "false");
    }
    public static Object categoryContent(String tid, String pg, boolean filter, HashMap<String,String> e) {
        return call("categoryContent", tid, pg);
    }
    public static Object searchContent(String key, boolean quick) {
        return call("searchContent", key);
    }
    public static Object detailContent(String[] ids) {
        return call("detailContent", ids != null && ids.length > 0 ? ids[0] : "");
    }
    /** ★ 播放解析：网盘资源在此分流（flag = baidu/quark/uc/aliyun） */
    public static Object playerContent(String flag, String id, String vipFlags) {
        return call("playerContent", flag, id);
    }

    /** 统一分发到 JS 规则的 spider.playerContent / searchContent 等 */
    private static Object call(String method, String... args) {
        try {
            Value bindings = context().getBindings("js");
            if (!bindings.hasMember("Spider")) return new JSONObject().toString();
            Value spider = bindings.getMember("Spider");
            // 默认走 'pan' 站点；多站点时按 flag 选 spider
            Value sp = spider.invokeMember("get", args.length > 0 ? args[0] : "pan");
            if (sp.hasMember(method)) {
                return sp.invokeMember(method, (Object[]) args).asString();
            }
            return new JSONObject().toString();
        } catch (Exception e) {
            JSONObject err = new JSONObject();
            err.put("url", args.length > 1 ? args[1] : "");
            err.put("type", 24);
            return err.toString();
        }
    }

    // 兼容：旧版影视仓可能调用无 vipFlags 的重载
    public static Object playerContent(String flag, String id) {
        return playerContent(flag, id, "");
    }
}
