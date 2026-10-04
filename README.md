# 外刊精读工作台

一个可本地启动的全栈产品：导入外刊文章，进入 PC/网页优先的精读阅读器，支持当前句高亮、划词释义、翻译、朗读、句型拆解、单词和重点句积累、笔记归档，以及 Markdown/PDF 导出。

## 技术栈

- 后端：Python 3 标准库 HTTP 服务
- 数据库：SQLite
- 前端：原生 HTML/CSS/JavaScript
- 依赖：无第三方运行依赖

选择这个栈是为了让项目在当前本地环境中稳定运行，不受包管理器或网络安装影响。

## 能力边界

- 离线演示：无需 API Key，内置 mock/规则版释义、翻译、全文赏析、精读训练和略读训练。
- 在线增强：设置 `FOREIGN_READING_AI_MODE=online` 并配置 `FOREIGN_READING_API_KEY` 后，释义、翻译、句型拆解和赏析接口会优先调用 OpenAI-compatible chat completions API。
- 朗读：默认使用浏览器 Web Speech。`FOREIGN_READING_TTS_ENDPOINT` 已预留给后续在线 TTS 服务。

## 启动

```powershell
python -m app.server --init-db
python -m app.server --host 127.0.0.1 --port 5178
```

打开：

```text
http://127.0.0.1:5178
```

## 环境变量

复制 `.env.example` 中的配置到你的运行环境即可。标准库版本不会自动读取 `.env` 文件；在 PowerShell 中可以这样设置：

```powershell
$env:FOREIGN_READING_AI_MODE="online"
$env:FOREIGN_READING_API_KEY="你的 API Key"
$env:FOREIGN_READING_API_BASE="https://api.openai.com/v1"
$env:FOREIGN_READING_MODEL="gpt-4o-mini"
python -m app.server
```

## 数据与迁移

- 迁移文件：`migrations/001_initial.sql`
- 默认数据库：`data/reading_lab.sqlite3`
- 首次启动会自动迁移并写入一篇演示文章：`The City That Learned to Listen`

主要数据表：

- `articles`：文章元数据与正文
- `paragraphs` / `sentences`：段落和句子结构
- `highlights`：高亮和备注
- `vocabulary`：单词积累
- `sentence_patterns`：重点句型
- `notes`：精读笔记
- `analysis_cache`：全文赏析缓存
- `reading_sessions`：当前句和阅读模式

## API 摘要

- `GET /api/articles`
- `POST /api/articles`
- `GET /api/articles/{id}`
- `GET /api/articles/{id}/analysis`
- `GET /api/articles/{id}/export?format=markdown`
- `GET /api/articles/{id}/export?format=pdf`
- `POST /api/tools/lookup`
- `POST /api/tools/translate`
- `POST /api/tools/sentence-analysis`
- `POST /api/highlights`
- `POST /api/vocabulary`
- `POST /api/patterns`
- `POST /api/notes`

## 测试

```powershell
python -m unittest discover -s tests
```

