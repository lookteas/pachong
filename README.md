# Pachong

`Pachong` 是一个面向现代文档站和动态网站的爬虫工具。它的核心目标不是“写一个一次性的抓取脚本”，而是提供一套可以持续适配新站点的工作流：

1. 先分析页面结构
2. 再生成站点配置草稿
3. 然后执行单页抓取或批量抓取
4. 最终输出 HTML、Markdown、JSON、截图和目录索引

当前项目已经可以稳定处理一类典型场景：

- 动态渲染页面抓取
- 基于站点配置的正文提取
- `jjjshop` 文档站左侧栏目批量抓取
- 新站点页面分析与配置草稿生成

## 核心能力

- `crawl`
  用于单页抓取。适合先验证一个页面能不能干净拿到标题、正文和图片。

- `batch`
  用于批量抓取。当前已针对 `jjjshop` 文档站实现，能够递归左侧菜单并批量保存页面内容。

- `analyze`
  用于新站点分析。自动抓取页面 HTML 和截图，识别标题、正文、菜单、噪音区域，并生成 `site_config.yaml` 配置草稿。

## 当前支持的站点形态

- `jjjshop`
  典型特征：左侧多级菜单，点击后右侧正文切换。

- `CRMEB`
  典型特征：标准文档详情页结构，正文区、右侧大纲、评论区、操作区混合存在。

项目并不是把所有网站硬编码成独立爬虫，而是通过：

- 通用抓取内核
- 站点配置文件
- 必要时的站点专用批量逻辑

来逐步扩展更多站点。

## 安装

```bash
pip install -e .
playwright install chromium
```

如果你刚更新过代码或依赖定义，建议重新执行一次：

```bash
pip install -e .
```

## 快速开始

### 1. 单页抓取

```bash
pachong crawl "https://example.com/article/123"
```

默认会输出到：

- `data/html/`
- `data/markdown/`
- `data/json/`
- `data/screenshots/`

### 2. 使用站点配置抓取

`jjjshop` 示例：

```bash
pachong crawl "https://doc.jjjshop.net/multi?category_id=10026&document_id=116" --config configs/sites/jjjshop_doc.yaml
```

`CRMEB` 示例：

```bash
pachong crawl "https://doc.crmeb.com/mer/mer3_4/33374" --config configs/sites/crmeb_doc.yaml
```

### 3. 分析新站点

遇到一个还没适配的新站，建议先分析：

```bash
pachong analyze "https://doc.crmeb.com/mer/mer3_4/33374"
```

分析结果会输出到类似目录：

- `data/analyze/<site_name>/<timestamp>/page.html`
- `data/analyze/<site_name>/<timestamp>/page.png`
- `data/analyze/<site_name>/<timestamp>/report.json`
- `data/analyze/<site_name>/<timestamp>/site_config.yaml`

其中：

- `report.json` 是分析报告
- `site_config.yaml` 是可继续调整并复用的配置草稿

### 4. 批量抓取 jjjshop 左侧栏目

```bash
pachong batch "https://doc.jjjshop.net/multi?category_id=10026&document_id=116"
```

默认输出到：

- `data/batch/jjjshop_doc/category_10026/markdown/`
- `data/batch/jjjshop_doc/category_10026/html/`
- `data/batch/jjjshop_doc/category_10026/toc.json`
- `data/batch/jjjshop_doc/category_10026/目录总览.md`

不同 `category_id` 会自动输出到不同目录，避免覆盖。

## 推荐工作流

这是目前最推荐的使用顺序：

### 场景一：新站点接入

1. 先执行 `analyze`
2. 查看 `report.json` 和页面截图
3. 调整 `site_config.yaml`
4. 使用 `crawl --config` 验证单页抓取质量
5. 如果页面是目录页，再决定是否做批量抓取

### 场景二：已适配站点批量抓取

1. 先用 `crawl --config` 验证一个页面
2. 确认 Markdown 输出没问题
3. 再执行 `batch`
4. 查看 `目录总览.md`

## 为什么要有站点配置

不同文档站虽然都是“左边目录、右边正文”，但底层结构差异非常大。一个稳定的爬虫项目，不能只靠一个通用 `article` 规则就试图适配所有站点。

站点配置主要解决这些问题：

- 标题在哪
- 正文在哪
- 菜单在哪
- 哪些区域是噪音
- 页面什么时候算加载完成
- 批量抓取时应该点哪里

当前配置文件主要包括：

- `fetch`
  定义等待策略、超时、正文加载判断等。

- `extract`
  定义标题 selector、正文 selector、要移除的噪音区域等。

- `output`
  定义是否保存 HTML、Markdown、JSON、截图。

## analyze 的定位

`analyze` 不是万能自动适配器，但它能显著减少人工试错时间。

它当前会尝试识别：

- 标题 selector
- 正文候选区域
- 菜单候选区域
- 需要剔除的噪音区域

它更像“站点配置草稿生成器”，而不是“完全自动决定一切”的黑盒。推荐做法是：

1. 让 `analyze` 先给出建议
2. 人工快速确认
3. 保存为正式配置

## 项目结构

```text
pachong/
├── README.md
├── pyproject.toml
├── configs/
│   └── sites/
│       ├── example_article.yaml
│       ├── jjjshop_doc.yaml
│       └── crmeb_doc.yaml
├── src/
│   └── pachong/
│       ├── cli.py
│       ├── runner.py
│       ├── analyze.py
│       ├── extractors/
│       ├── fetchers/
│       ├── models/
│       ├── sites/
│       │   └── jjjshop_batch.py
│       ├── storage/
│       └── utils/
├── tests/
└── 爬取动态渲染网站.md
```

## 重要输出说明

### 单页抓取输出

- HTML：保留原始页面结构，便于排查
- Markdown：适合人工阅读和知识沉淀
- JSON：适合程序消费和后续处理
- 截图：用于快速确认页面是否真正加载完成

### 批量抓取输出

- 每页一个 Markdown 文件
- 每页一个 HTML 文件
- `toc.json`：机器可读索引
- `目录总览.md`：人可读目录

## 已实现的关键设计

- 使用 `Playwright` 处理动态页面
- 等待正文节点真正有内容后再抓取
- 正文区域优先使用 HTML 转 Markdown，避免纯图片页面被裁掉
- `jjjshop` 支持同一页面内递归点击左侧菜单
- 批量目录会自动生成带链接和摘要的总览文档
- `batch` 输出目录按 `category_id` 自动隔离，避免互相覆盖
- `analyze` 能为新站生成配置草稿

## 当前边界

当前项目已经能解决“接入新文档站”和“抓取站内文档”的大部分基础问题，但仍有一些能力尚未完善：

- `CRMEB` 批量抓取尚未正式接入
- `analyze` 还没有自动判断“是否建议启动批量抓取”
- 还没有统一的批量任务调度与断点续跑系统
- 还没有网络接口监听抓取能力
- 还没有 SQLite 状态管理

## 适合下一步继续做的方向

- 增强 `analyze`
  增加页面分类能力，判断当前页是正文页、目录页还是混合页。

- 扩展 `batch`
  从 `jjjshop` 专用批量抓取，逐步演进为“站点适配器 + 通用批量入口”。

- 增加任务存储
  记录抓取状态、失败原因、重试信息和断点续跑信息。

- 增加接口抓取
  针对 SPA 文档站，直接分析并抓取 XHR/fetch 数据。

## 提交说明

如果你已经初始化了仓库，推荐先完成：

```bash
git add .
git commit -m "feat: bootstrap crawler, analysis, and jjjshop batch workflow"
```

## 备注

设计思路文档保存在：

[爬取动态渲染网站.md](/d:/code/python/pachong/爬取动态渲染网站.md)

如果你准备继续扩展更多站点，建议以后都遵循这条路线：

`analyze -> 生成配置草稿 -> 单页验证 -> 批量抓取`

这样成本最低，也最稳。
