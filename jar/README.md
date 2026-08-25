# Spider 爬虫说明

本目录存放影视仓使用的 spider.jar，负责：
  - 百度网盘 / 夸克网盘 / UC网盘 / 阿里云盘 的分享链接解析
  - 复杂动态站点（JS 渲染、加密参数）的采集

## 如何获取/更新 spider.jar
方案 A（推荐，开箱即用）：
  直接使用开源社区维护的通用 spider，例如：
    - https://github.com/FongMi/ 系列
    - 将 jar 下载后放入本目录，命名为 spider.jar

方案 B（自建，完全可控）：
  参考 tvbox-config 类仓库，编写 drpy2 规则（FTY/*.js），
  打包进 spider.jar，在单仓里通过 "jar" + "spider" 字段引用。

## 网盘 flag 映射（单仓 flags 字段）
  baidu  -> type 18
  quark  -> type 19
  uc     -> type 20
  aliyun -> type 21

影视仓播放网盘资源时，会按 flags 里的 flag 路由到对应解析逻辑。
