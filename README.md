# 自建影视仓聚合片源

多仓 + 单仓自动生成，三档健康检查（valid/nav/dead）+ UA 模拟 + 二次探测，
GitHub Actions 每 3 天自动更新并部署到 GitHub Pages。

## 目录
- `sources.yaml`  上游线路池（**你只改这一个文件**）
- `scripts/generate.py`  生成器（三档健康检查 + 二次探测）
- `scripts/test_generate.py`  本地自测（5 大类单测）
- `index.json`  最终产物（多仓入口，供影视仓配置地址）
- `lines/`  生成的单仓文件
- `.github/workflows/deploy.yml`  CI（生成 → Pages 部署）

## 本地使用
```bash
python3 scripts/test_generate.py      # 跑单测
python3 scripts/generate.py --check   # 仅健康检查报告（不写文件）
python3 scripts/generate.py           # 完整生成 index.json + lines/
```

## 改源（永久生效）
编辑 `sources.yaml` 的 `lines:` / `warehouses:`，提交推送即可。
CI 会自动重新生成。无需手动改 `lines/`。

## 影视仓配置地址
```
https://<你的用户名>.github.io/<仓库名>/index.json
```

## Secrets（可选）
`ALIYUN_REFRESH_TOKEN` / `BAIDU_COOKIE` / `QUARK_COOKIE` / `UC_COOKIE`
不设也能跑 spider 骨架；填了走直连不弹码。
