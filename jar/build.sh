#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

JAR="spider.jar"
LIB="lib"
mkdir -p "$LIB" build spider/js

echo "[1/5] 探测 JDK / GraalVM ..."
JAVAC="${JAVAC:-$(command -v javac || true)}"
if [ -z "$JAVAC" ]; then
  for p in "$GRAALVM_HOME" "$HOME/.sdkman/candidates/java/current" "/usr/lib/jvm/graalvm"; do
    [ -x "$p/bin/javac" ] && JAVAC="$p/bin/javac" && break
  done
fi
if [ -z "$JAVAC" ]; then
  echo "⚠️ 未找到 javac，生成占位 spider.jar（JS 规则仍需由 CatVod 壳子/CI GraalVM 提供运行时）"
  mkdir -p build/pkg/META-INF
  cat > build/pkg/META-INF/MANIFEST.MF <<'EOF'
Manifest-Version: 1.0
Created-By: yingshicang self-host (stub)
Main-Class: spider.Main
EOF
  ( cd build/pkg && jar cf "../../$JAR" . ) 2>/dev/null || ( cd build/pkg && zip -r "../../$JAR" . >/dev/null )
  echo "     ✅ 占位 $JAR 已生成（CI/GraalVM 环境会替换为真实 jar）"
  ls -lh "$JAR" 2>/dev/null || echo "     ℹ️ 跳过 jar 校验（无 jar 命令）"
  exit 0
fi
echo "     使用: $JAVAC"

JAVA_HOME_DIR="$(dirname "$(dirname "$JAVAC")")"
if "$JAVAC" -version 2>&1 | grep -qi "graalvm"; then
  HAS_GRAAL=true; echo "     ✅ 检测到 GraalVM（将打包 GraalJS 引擎，JS 规则可用）"
else
  HAS_GRAAL=false; echo "     ⚠️ 非 GraalVM（JS 规则不可用，仅 Java 骨架；生产建议用 GraalVM）"
fi

echo "[2/5] 检查依赖 json.jar ..."
JSON_JAR="$LIB/json.jar"
if [ ! -f "$JSON_JAR" ]; then
  echo "     下载 org.json:json ..."
  curl -sL -o "$JSON_JAR" "https://repo1.maven.org/maven2/org/json/json/20240303/json-20240303.jar" \
    || curl -sL -o "$JSON_JAR" "https://search.maven.org/remotecontent?filepath=org/json/json/20240303/json-20240303.jar"
fi
[ -f "$JSON_JAR" ] && echo "     ✅ $JSON_JAR ($(du -h "$JSON_JAR" | cut -f1))" || echo "     ⚠️ 未下载到 json.jar"

echo "[3/5] 编译 Java 源 ..."
CP="$JSON_JAR"
if [ "$HAS_GRAAL" = true ]; then
  GRAAL_FLAGS="--add-exports=org.graalvm.js/js.scriptengine=ALL-UNNAMED"
fi
rm -rf build/*
"$JAVAC" ${GRAAL_FLAGS:-} -cp "$CP" -d build spider/Main.java spider/Spider.java 2>&1 | tee /tmp/javac.log
[ "${PIPESTATUS[0]}" -ne 0 ] && { echo "❌ 编译失败"; exit 1; }

echo "[4/5] 打包 $JAR ..."
rm -f "$JAR"
PKG=build/pkg
rm -rf "$PKG" && mkdir -p "$PKG/spider/js"
cp build/spider/*.class "$PKG/spider/" 2>/dev/null

if [ "$HAS_GRAAL" = true ]; then
  cp spider/js/*.js "$PKG/spider/js/" 2>/dev/null && echo "     ✅ 已打入 JS 规则: $(ls spider/js/*.js | wc -l) 个"
fi

cat > "$PKG/config.json" <<'EOF'
{
  "aliyun": { "refresh_token": "${ALIYUN_REFRESH_TOKEN:-}" }
}
EOF

mkdir -p "$PKG/META-INF"
cat > "$PKG/META-INF/MANIFEST.MF" <<EOF
Manifest-Version: 1.0
Created-By: yingshicang self-host
Main-Class: spider.Main

EOF

( cd "$PKG" && jar cf "../../$JAR" . )
echo "     ✅ $JAR ($(du -h "$JAR" | cut -f1))"

echo "[5/5] 校验 jar 结构 ..."
JAVA_BIN="$(dirname "$JAVAC")/java"
"$JAVA_BIN" -cp "$JAR:$JSON_JAR" spider.Main 2>&1 | head -10 || true
echo "--- jar 内容 ---"
jar tf "$JAR" | grep -E "\.(class|js|json)$"

echo ""
echo "=========================================="
echo "✅ 构建完成: $(pwd)/$JAR"
echo "   影视仓单仓引用: \"jar\": \"jar/spider.jar\""
echo "=========================================="
