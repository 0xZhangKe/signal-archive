# Signal Archive

Signal Archive 是一个基于 GitHub Actions 的自动化内容采集与归档项目。项目从标准 RSS/Atom 订阅源和 AI 驱动的自定义订阅源拉取内容，将结果保存到独立的 `archive` 分支，并使用 Git commit 记录每次归档的变化。归档数据可以被 Fread、GitHub Pages 以及其他阅读端共同使用。

[https://0xzhangke.github.io/signal-archive/](https://0xzhangke.github.io/signal-archive/)

## 分支职责

### `main`

保存项目配置和采集程序：

```text
main
├── opml.xml
├── scripts/
│   ├── generate_catalog.py
│   └── fetch_rss.py
├── tests/
└── .github/workflows/
    ├── sync-catalog.yml
    └── fetch-rss.yml
```

### `archive`

保存供不同阅读端使用的 Catalog 和归档后的 Feed 文档：

```text
archive
├── catalog.json
├── source_state.json
├── rendered.json
├── rss/
│   ├── <feed-hash>.xml
│   └── ...
├── categories/
│   ├── <source-id>/
│   └── folder-<title-hash>/
├── articles/
│   ├── <article-id>.json
│   └── ...
└── ai/
    ├── <prompt-name>.xml
    └── ...
```

`archive` 是独立的 orphan 分支，不需要包含 `opml.xml`、脚本或 GitHub Actions。

其中 `catalog.json`、`source_state.json`、`rss/` 和 `ai/` 是归档数据；`rendered.json`、`categories/` 和 `articles/` 是 Pages 构建阶段生成并同步回 `archive` 的阅读端数据。

## 内容来源

### RSS/Atom

标准订阅源及其分类层级维护在 [`opml.xml`](./opml.xml) 中。归档任务只保存 RSS/Atom 文档本身，不下载或拆分其中的文章正文。

RSS 文档使用规范化 Feed URL 的 SHA-256 哈希前 16 位命名，例如：

```text
rss/61b927a83d72e9f0.xml
```

因此，修改 OPML 中的分类或显示标题不会移动已经归档的 Feed 文件。

### AI 自定义订阅源

AI 订阅源将通过 Prompt 列表描述需要采集的主题、范围和输出要求，并调用指定 AI API 获取内容。AI 返回结果也会转换为标准 Feed 文档，使不同阅读端能够用统一方式读取 RSS 和 AI 内容。

API Key 等敏感信息必须通过 GitHub Actions Secrets 管理，不得提交到仓库。

由于 `rss/`、`ai/` 以及由它们生成的 `categories/`、`articles/` 保存第三方公开内容，其中的示例代码可能包含与凭据格式相似的字符串。项目通过 [`.github/secret_scanning.yml`](./.github/secret_scanning.yml) 将这些自动生成目录排除在 Secret Scanning 和 push protection 之外，避免归档任务被误报阻断。项目代码、Workflow、OPML、Catalog 和 `rendered.json` 不在排除范围内，仍接受正常的凭据扫描。

## Catalog

`archive/catalog.json` 是由 OPML 自动生成的内容导航与来源索引。它保留 OPML 的分类层级，但不复制 OPML 文件，也不要求归档文件夹遵循分类层级。阅读端通过 Catalog 构建导航，再通过 `feedPath` 获取相应的 Feed 文档。

示例：

```json
{
  "startedAt": "2026-07-23T02:00:00Z",
  "finishedAt": "2026-07-23T02:03:18Z",
  "durationSeconds": 198,
  "children": [
    {
      "type": "category",
      "title": "技术",
      "children": [
        {
          "type": "rss",
          "title": "OpenAI News",
          "feedPath": "rss/61b927a83d72e9f0.xml",
          "originalUrl": "https://example.com/feed.xml",
          "lastSuccessfulFetchAt": null,
          "lastContentChangedAt": null
        }
      ]
    }
  ]
}
```

节点分为两类：

- `category`：显示一个分类，通过 `children` 包含下级分类或订阅源。
- `rss`：显示一个 RSS/Atom 订阅源，通过 `feedPath` 指向归档文件。

后续 AI 订阅源使用 `type: "ai"`，同样通过 `feedPath` 指向可读取的 Feed 文档。

时间字段的含义：

- `lastSuccessfulFetchAt`：最近一次成功拉取该来源的时间。
- `lastContentChangedAt`：归档 Feed 内容最近一次实际变化的时间。

首次生成时两个字段都是 `null`。重新生成 Catalog 时，脚本会根据稳定的 `feedPath` 继承已有时间，避免 OPML 分类或标题变化导致运行状态丢失。

## 阅读端

`archive` 分支同时提供原始 Feed 和预渲染 JSON，不绑定某一种阅读方式。计划支持的阅读端包括：

- Fread：读取 `rendered.json`、分页列表和文章详情。
- GitHub Pages：使用相同的预渲染 JSON 展示静态阅读页面。
- 其他客户端或服务：可以直接使用预渲染 JSON，也可以读取 Catalog 和原始 Feed 做独立处理。

各阅读端共享同一份归档与渲染数据，可以采用不同的页面结构、交互方式和本地状态管理。已读状态、收藏等客户端专属数据不写入公共归档文件。

## GitHub Pages

[`deploy-pages.yml`](./.github/workflows/deploy-pages.yml) 使用 [`build_pages.py`](./scripts/build_pages.py) 解析 `archive` 中的 Catalog 与 Feed，并与 `main` 分支的 `site/` 静态页面组合为 GitHub Pages Artifact：

```text
archive/catalog.json + archive/rss/*.xml + archive/source_state.json
                              ↓
                    deploy-pages 渲染阶段
                    ┌─────────┴─────────┐
                    ↓                   ↓
       archive/rendered data      main/site/ + rendered data
                    ↓                   ↓
            commit 到 archive      GitHub Pages Artifact
```

RSS 拉取工作流成功更新 `archive` 后会发送 `archive_updated` 事件并自动部署 Pages。人工修改 `archive` 后可以从 GitHub Actions 页面手动运行 `Deploy GitHub Pages`。

首次使用时，需要在仓库中选择：

```text
Settings → Pages → Build and deployment → Source → GitHub Actions
```

Pages Artifact 本身仍然只用于 GitHub Pages 部署，不提交到分支；但其中的 `rendered.json`、`categories/` 和 `articles/` 会在部署前同步并提交到 `archive`，供其他客户端直接读取。同步使用完整镜像语义，已经失效的分页和文章详情文件会从 `archive` 删除。

构建阶段不会改写 `archive/rss/*.xml`，也不会把原始 `catalog.json` 复制到 Pages Artifact。页面只使用渲染后的 JSON：

```text
data/
├── rendered.json
├── source_state.json
├── categories/
│   ├── <source-id>/
│   │   ├── page-001.json
│   │   └── ...
│   └── folder-<title-hash>/
│       ├── page-001.json
│       └── ...
└── articles/
    ├── <article-id>.json
    └── ...
```

`rendered.json` 保留一级文件夹和 source 导航。深层 Category 会拍平到所属的一级 Category。每个文件夹和 source 都通过 `pages` 指向自己的分页文章列表，每页最多 60 篇。source 目录使用 Catalog 中 `feedPath` 的文件名部分；文件夹目录使用规范化标题的 SHA-256 前 16 位，并添加 `folder-` 前缀。OPML 中的文件夹标题必须全局唯一。

示例：

```json
{
  "children": [
    {
      "type": "category",
      "title": "中文博客",
      "articleCount": 2607,
      "failed_count": 2,
      "pages": [
        "categories/folder-08f18aa4658e8149/page-001.json"
      ],
      "children": [
        {
          "articleCount": 83,
          "state": 0.933333,
          "pages": [
            "categories/05ada84875558017/page-001.json"
          ],
          "lastContentChangedAt": "2026-07-22T09:27:38Z",
          "lastSuccessfulFetchAt": "2026-07-23T02:01:17Z",
          "originalUrl": "https://blog.solazy.me/feed",
          "title": "So!azy",
          "type": "rss"
        }
      ]
    }
  ]
}
```

每个 folder 和 source 节点都包含 `articleCount`。source 使用对应 Feed 的文章数量；folder 使用所有后代 source 按文章 ID 去重后的聚合数量。

RSS 节点还包含 `state`，取值范围为 `0.0` 到 `1.0`，计算方式为最近 15 天 `source_state.json` 中的成功次数除以总拉取次数，保留 6 位小数。没有拉取记录时使用 `1.0`。Category 节点的 `failed_count` 表示最近一轮拉取中，其后代 source 失败的数量。

`rendered.json` 根节点的 `startedAt`、`finishedAt` 和 `durationSeconds` 来自 `source_state.json` 中完成时间最新的一轮拉取。Pages 左栏只使用 `startedAt` 显示最近一轮开始拉取的时间。RSS 成功率低于 `1.0` 时，左栏标题前显示从陶土红到赭黄色变化的状态点；成功率为 `1.0` 时不显示。二栏会在文章总数前显示当前 Category 的失败数，或当前 RSS 的成功率。

分页文件只保存列表展示所需的摘要信息，并通过 `detailPath` 指向 `articles/<article-id>.json`。文章详情包含经过安全清理的 HTML，只有打开文章时才会加载。

```json
{
  "id": "ab01cd23ef45ab01cd23ef45",
  "title": "Article title",
  "summary": "A short plain-text summary.",
  "content": "<p>Sanitized article HTML...</p>",
  "image": null,
  "publishedAt": "2026-07-23T02:01:17Z",
  "sourceId": "05ada84875558017",
  "sourceTitle": "So!azy",
  "link": "https://blog.solazy.me/posts/example"
}
```

因此，阅读页面选择大型文件夹时不需要在浏览器中临时下载和解析大量 XML。

### 本地 UI 预览

运行本地 mock 预览：

```bash
python3 scripts/preview_pages.py
```

然后打开 [http://127.0.0.1:4173/](http://127.0.0.1:4173/)。Mock 数据覆盖 folder 展开、成功率、最近失败数、长标题、有图与无图文章、富文本正文以及超过 60 篇文章的分页场景。预览服务直接读取 `site/`，修改 HTML、CSS 或 JavaScript 后刷新页面即可看到结果。

如果只需要重新生成 `_mock_preview/` 数据而不启动服务：

```bash
python3 scripts/preview_pages.py --build-only
```

## 生成 Catalog

本地运行：

```bash
python3 scripts/generate_catalog.py \
  --input opml.xml \
  --output catalog.json
```

如果需要从旧 Catalog 继承拉取状态：

```bash
python3 scripts/generate_catalog.py \
  --input opml.xml \
  --existing path/to/old/catalog.json \
  --output path/to/new/catalog.json
```

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

## 自动同步

[`sync-catalog.yml`](./.github/workflows/sync-catalog.yml) 在以下文件被推送到 `main` 时自动运行：

- `opml.xml`
- `scripts/generate_catalog.py`
- `tests/test_generate_catalog.py`
- `.github/workflows/sync-catalog.yml`

也可以从 GitHub Actions 页面手动触发。工作流会：

1. 检出 `main` 并读取 OPML。
2. 检出已有的 `archive`；如果不存在，则首次创建 orphan 分支。
3. 生成 `archive/catalog.json`，同时继承已有时间字段。
4. 仅在 Catalog 发生变化时创建 commit。
5. 将 commit 推送到远端 `archive` 分支。

所有会写入 `archive` 的工作流都应使用 `signal-archive-writer` 并发组，避免多个任务同时推送产生冲突。

## RSS 自动拉取

[`fetch-rss.yml`](./.github/workflows/fetch-rss.yml) 从 `archive/catalog.json` 读取 RSS 节点，并将每个 `originalUrl` 的 RSS/Atom 文档保存到对应的 `feedPath`。同一个来源出现在多个分类中时只会下载一次，但所有对应节点的时间字段都会同步更新。

工作流在以下情况运行：

- `catalog.json` 实际发生变化并由 Catalog 同步工作流成功推送后。
- 每天上海时间 02:00、08:00、14:00 和 20:00。
- 从 GitHub Actions 页面手动触发。

单个来源拉取失败不会丢弃其他来源已经成功拉取的结果。成功的来源会更新 `lastSuccessfulFetchAt`；只有 Feed 文档内容变化时才更新 `lastContentChangedAt`。

每轮拉取完成后还会更新 `archive/source_state.json`，保存最近 15 天的运行状态：

```json
[
  {
    "startedAt": "2026-07-23T00:00:00Z",
    "finishedAt": "2026-07-23T00:03:18Z",
    "durationSeconds": 198,
    "failed": [
      "05ada84875558017"
    ]
  }
]
```

`failed` 只保存失败来源的 16 位 URL 哈希，对应 Catalog 中 `feedPath` 的文件名部分。全部成功时仍保留该轮记录，并使用空数组。Pages Artifact 会包含 `data/source_state.json`，供阅读页面展示运行状态。

本地运行拉取器时，需要提供一个包含 Catalog 的归档目录：

```bash
python3 scripts/fetch_rss.py \
  --catalog path/to/archive/catalog.json \
  --archive-root path/to/archive
```

## 归档流程目标

```text
OPML ──> catalog.json ───────────────┐
                                     │
RSS/Atom URL ──> 原始 Feed 文档 ─────┼──> archive 分支单次 commit
                                     │
Prompt ──> 指定 AI API ──> Feed 文档 ┘
```

每轮采集完成后，本轮所有 Feed 更新和时间字段合并为一个 commit 并推送到 `archive`。因为成功拉取会更新 `lastSuccessfulFetchAt`，正常运行通常会产生一个 commit。Git 历史负责保存 Feed 文档的历史版本。
