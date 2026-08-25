# 自建影视仓聚合片源

> 自动生成于 2026-08-25 05:18:00
> 当前健康线路：**20** 条，失效：**0** 条

## 目录结构
```
.
├── index.json              # ★ 多仓入口（影视仓「配置地址」填这个）
├── lines/                  # 每条健康线路一个单仓 json
├── jar/spider.jar          # 网盘/复杂站点爬虫（百度·夸克·UC·阿里）
├── scripts/generate.py     # 本生成器
├── sources.yaml            # 上游线路池（可编辑，热更新）
└── backup/                 # 历史配置自动备份
```

## 使用方式
1. 把本目录部署到 **GitHub Pages / Gitee / 自建服务器**（需 HTTPS 公网可访问）
2. 影视仓 → 设置 → 配置地址 → 填入 `https://你的域名/index.json`
3. 如需多仓，仓库管理里再添加 index.json，自动展开所有线路

## 如何保证不突然失效
- ✅ 多仓结构：index.json 挂 N 条单仓，一条挂不影响其他
- ✅ 每条单仓配 `urlv` 备用地址 + 多 CDN 镜像
- ✅ 自动健康检查：crontab 每日跑 `python3 generate.py`，失效线路自动剔除
- ✅ 配置自动备份到 backup/，出问题可回滚
- ✅ 网盘源走 spider.jar 统一适配，规则可独立更新

## 定时更新（crontab 示例，每天 6 点刷新）
```
0 6 * * * cd /path/to/yingshicang && python3 scripts/generate.py >> scripts/update.log 2>&1
```

## 自定义上游
编辑 `sources.yaml`，按以下格式增删：
```yaml
lines:
  - name: 我的线路
    url: https://example.com/tvbox.json
    tags: [点播, 4K]
    priority: 1   # 1-3 主用，>3 备用
```
