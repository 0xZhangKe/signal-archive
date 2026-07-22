# Signal Archive

Signal Archive 是一个基于 GitHub Actions 的自动化内容采集与归档项目。项目从标准 RSS/Atom 订阅源和 AI 驱动的自定义订阅源拉取内容，将结果保存到独立的 `archive` 分支，并使用 Git commit 记录每次归档的变化。归档数据可以被 Fread、GitHub Pages 以及其他阅读端共同使用。

## 分支职责

### `main`

保存项目配置和采集程序：

```text
main
├── opml.xml
├── scripts/
├── tests/
└── .github/workflows/
```

### `archive`

保存供不同阅读端使用的 Catalog 和归档后的 Feed 文档：

```text
archive
├── catalog.json
├── rss/
│   ├── <feed-hash>.xml
│   └── ...
└── ai/
    ├── <prompt-name>.xml
    └── ...
```

`archive` 是独立的 orphan 分支，不需要包含 `opml.xml`、脚本或 GitHub Actions。

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

## Catalog

`archive/catalog.json` 是由 OPML 自动生成的内容导航与来源索引。它保留 OPML 的分类层级，但不复制 OPML 文件，也不要求归档文件夹遵循分类层级。阅读端通过 Catalog 构建导航，再通过 `feedPath` 获取相应的 Feed 文档。

示例：

```json
{
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

`archive` 分支提供与具体 UI 无关的数据层，不绑定某一种阅读方式。计划支持的阅读端包括：

- Fread：读取 Catalog 构建分类和订阅源列表，并解析对应 Feed 文档。
- GitHub Pages：将 Catalog 和 Feed 文档渲染为可以直接浏览的静态网站。
- 其他客户端或服务：按照相同的数据结构读取、搜索或聚合归档内容。

各阅读端共享同一份 Catalog 和 Feed 文档，可以采用不同的页面结构、交互方式和本地状态管理。已读状态、收藏等客户端专属数据不写入公共归档文件。

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

## 归档流程目标

```text
OPML ──> catalog.json ───────────────┐
                                     │
RSS/Atom URL ──> 原始 Feed 文档 ─────┼──> archive 分支单次 commit
                                     │
Prompt ──> 指定 AI API ──> Feed 文档 ┘
```

每轮采集完成后，本轮所有新增或更新内容合并为一个 commit 并推送到 `archive`。没有变化时不创建内容 commit。Git 历史负责保存 Feed 文档的历史版本。
