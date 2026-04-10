# Pachong

`Pachong` 是一个面向现代文档站和动态网站的爬虫工具。项目的目标不是生成一次性的站点脚本，而是建立一套稳定的站点适配流程：

`analyze -> 生成配置草稿 -> 单页验证 -> 批量抓取`

当前项目重点覆盖以下场景：

- 动态渲染页面抓取
- 基于配置的标题与正文提取
- 新站点分析与配置草稿生成
- `jjjshop` 文档站的左侧菜单批量抓取

## 项目架构

项目分为三层：

### 1. 抓取内核

负责页面访问、等待加载、截图、HTML 获取。

核心组件：

- `PlaywrightFetcher`
- `runner.py`

### 2. 提取层

负责根据配置提取标题、正文和清理噪音区域。

核心组件：

- `ArticleExtractor`
- `configs/sites/*.yaml`

### 3. 站点适配层

负责处理某类站点的特殊批量逻辑或菜单遍历逻辑。

当前已有：

- `jjjshop_batch.py`

## 功能说明

### `crawl`

抓取单个页面，输出：

- HTML
- Markdown
- JSON
- 页面截图

适合用来：

- 验证站点配置是否正确
- 检查标题和正文是否提取干净
- 为后续批量抓取做前置验证

### `batch`

当前用于 `jjjshop` 文档站的批量抓取。

能力包括：

- 递归左侧菜单
- 逐项点击页面
- 逐页保存 Markdown 和 HTML
- 自动生成目录索引文档
- 按 `category_id` 自动分目录，避免覆盖

### `analyze`

用于新站点页面分析。

能力包括：

- 抓取 HTML 快照和页面截图
- 识别标题候选 selector
- 识别正文候选 selector
- 识别菜单候选 selector
- 识别需要剔除的噪音区域
- 生成 `report.json`
- 生成 `site_config.yaml` 配置草稿

## 技术实现

### 动态页面抓取

使用 `Playwright` 访问页面，并支持：

- `wait_selector`
- `wait_for_text_selector`
- `delay_after_load_ms`

这保证了页面不是“刚打开就抓”，而是等正文区域真正有内容之后再抓取。

### 正文提取

正文提取优先采用“正文节点 HTML -> Markdown”的方式，避免纯图片内容或结构化文档被过度裁剪。

当前提取链路大致是：

1. 先定位 `content_selector`
2. 对正文节点做噪音清理
3. 将正文 HTML 转换为 Markdown
4. 必要时回退到 `trafilatura`

### 站点配置

站点配置文件位于：

- `configs/sites/example_article.yaml`
- `configs/sites/jjjshop_doc.yaml`
- `configs/sites/crmeb_doc.yaml`

配置主要分为三部分：

- `fetch`
- `extract`
- `output`

这样做的目的是把“站点适配”从代码里拆出来，优先通过配置解决不同网站的结构差异。

## 使用说明

### 安装

```bash
pip install -e .
playwright install chromium
```

如果更新过代码或依赖定义，建议重新执行：

```bash
pip install -e .
```

### 单页抓取

```bash
pachong crawl "https://example.com/article/123"
```

使用专用站点配置：

```bash
pachong crawl "https://doc.jjjshop.net/multi?category_id=10026&document_id=116" --config configs/sites/jjjshop_doc.yaml
```

```bash
pachong crawl "https://doc.crmeb.com/mer/mer3_4/33374" --config configs/sites/crmeb_doc.yaml
```

### 分析新站点

```bash
pachong analyze "https://doc.crmeb.com/mer/mer3_4/33374"
```

默认会生成：

- 页面 HTML 快照
- 页面截图
- `report.json`
- `site_config.yaml`

### 批量抓取 jjjshop

```bash
pachong batch "https://doc.jjjshop.net/multi?category_id=10026&document_id=116"
```

默认输出目录示例：

- `data/batch/jjjshop_doc/category_10026/markdown/`
- `data/batch/jjjshop_doc/category_10026/html/`
- `data/batch/jjjshop_doc/category_10026/toc.json`
- `data/batch/jjjshop_doc/category_10026/目录总览.md`

不同 `category_id` 会自动分目录，避免覆盖。

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
├── docs/
│   └── DEVLOG.md
├── src/
│   └── pachong/
│       ├── cli.py
│       ├── runner.py
│       ├── analyze.py
│       ├── extractors/
│       ├── fetchers/
│       ├── models/
│       ├── sites/
│       ├── storage/
│       └── utils/
├── tests/
└── 爬取动态渲染网站.md
```

## 输出说明

### 单页抓取输出

- HTML：用于排查页面结构
- Markdown：用于阅读、沉淀和后处理
- JSON：用于程序消费
- 截图：用于确认页面是否正确加载

### 批量抓取输出

- 每页一个 Markdown
- 每页一个 HTML
- `toc.json`：机器可读索引
- `目录总览.md`：人可读目录

## 开发日志

项目阶段性进展、已实现能力、当前边界和后续方向，统一记录在：

[DEVLOG.md](/d:/code/python/pachong/docs/DEVLOG.md)
