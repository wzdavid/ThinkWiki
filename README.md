# ThinkWiki

`ThinkWiki` 是一个符合 Agent Skills 规范的本地 Markdown 知识库 skill。它帮助 Agent 持续整理、沉淀、查询和可视化你的知识库，而不是每次都从原始资料重新推导。

## 效果预览

下面这三张样例图展示了 `ThinkWiki` 生成后的三个核心成果页：

- 成果入口页：用户最容易直接打开的统一入口，也会展示当前 wiki 的页面规模和图谱状态
- 浏览页：适合按页面类型、状态、置信度浏览整个 wiki
- 图谱页：适合查看页面之间的引用、包含和链接关系
- 这三张图都来自仓库内 `docs/demo-wiki` 的真实输出，而不是手工绘制的示意图

### 成果入口页样例

![ThinkWiki Output Hub Preview](docs/assets/output-hub-preview.png)

### 浏览页样例

![ThinkWiki Viewer Preview](docs/assets/viewer-preview.png)

### 图谱页样例

![ThinkWiki Graph Preview](docs/assets/graph-preview.png)

## 30 秒上手

安装好 `ThinkWiki` 之后，最自然的使用方式通常是直接通过 Agent 对话来使用它。

你可以直接对 Agent 这样说：

- “帮我初始化一个知识库，名字叫 `My Wiki`”
- “把这个 PDF 导入到知识库里：`/path/to/file.pdf`”
- “把这个网页整理进知识库：`https://example.com/article`”
- “基于当前知识库回答：AI 原生团队的核心定义是什么？”
- “帮我生成一个本地知识图谱，我想可视化看看”

如果宿主支持工具自动调用，Agent 会直接使用 `ThinkWiki` 完成这些动作；对最终用户来说，通常不需要手动记住底层命令。

## 它能做什么

- 初始化本地 wiki 工作区
- 导入 Markdown、PDF、DOCX、XLSX、XLS、PPTX、网页和文本
- 基于已有知识页做证据优先问答
- 将高价值结果沉淀为 `query / synthesis / decision / concept`
- 生成本地浏览页和离线知识图谱
- 检查运行时依赖、结构和链接健康度

## 为什么适合作为 Agent Skill

`ThinkWiki` 的目标就是作为一个完整 skill 被安装和使用，而不是依赖额外 companion skills 或复杂安装器。

- 整个仓库就是一个 skill
- 统一入口是 `scripts/thinkwiki`
- 首次运行时会自举仓库内 `.venv`
- 运行依赖来自仓库内 `requirements.txt`
- 支持 macOS、Linux 和 Windows
- 不要求用户理解内部脚本结构
- 不要求前端工程或服务端环境

对宿主来说，只需要安装 `ThinkWiki` 这一个 skill；对用户来说，只需要围绕知识库说自然语言需求。

## 你会得到什么

一个典型知识库会长成这样：

```text
<wiki-root>/
├── raw/
├── normalized/
├── wiki/
│   ├── sources/
│   ├── topics/
│   ├── concepts/
│   ├── decisions/
│   ├── syntheses/
│   └── queries/
├── output/
│   ├── graph/
│   │   ├── graph.json
│   │   ├── graph.md
│   │   └── index.html
│   ├── viewer/
│       ├── viewer.json
│       └── index.html
│   └── index.html
├── .wiki-schema.md
├── index.md
├── overview.md
├── purpose.md
└── log.md
```

其中：

- `wiki/` 保存沉淀后的知识页面
- `output/viewer/index.html` 是本地浏览页
- `output/graph/index.html` 是本地知识图谱
- `output/index.html` 是统一成果入口页
- 这些成果都可以直接在浏览器打开查看

## 和普通 RAG 的区别

`ThinkWiki` 更强调“持续沉淀”而不是“一次问答”：

- Markdown 和文件系统是本地真相源
- 来源、摘要、证据和派生页面都可追溯
- 索引和派生内容都可重建
- 可以直接离线浏览页面和图谱

## 安装方式

### 作为 Agent Skills 使用

`ThinkWiki` 的真实使用方式是把它作为一个 skill 安装到支持 Agent Skills 的宿主里。

适用宿主包括但不限于：

- Trae
- Claude Code
- OpenClaw
- Hermes Agent
- 其他支持本地 Agent Skills 目录的宿主

通用安装原则：

- 保留整个 `ThinkWiki` 仓库目录，不要只复制单个脚本
- 把仓库放到宿主约定的 skills 目录中
- 实际执行入口统一是 `<python-command> scripts/thinkwiki <command> ...`
- 首次运行时让 `ThinkWiki` 自己完成 `.venv` 自举和依赖安装

以 Trae 为例，典型结构如下：

```text
<workspace>/.trae/skills/
└── ThinkWiki
```

如果你通过 Git 拉取源码，推荐直接克隆到宿主的 skills 目录，例如：

```bash
git clone https://github.com/wzdavid/ThinkWiki ThinkWiki
cd ThinkWiki
<python-command> scripts/thinkwiki bootstrap
<python-command> scripts/thinkwiki doctor --repo-root .
```

说明：

- 首次执行 `bootstrap` 时会在仓库内自动创建 `./.venv`
- 这个本地运行环境仅供 `ThinkWiki` 自己使用，不需要手动激活
- `.venv/` 已加入仓库忽略规则，不应提交到 Git
- 对用户来说，只需要安装 `ThinkWiki` 这一个 skill

其中：

- 文中的 `<python-command>` 在 macOS / Linux 上通常是 `python3`
- 文中的 `<python-command>` 在 Windows 上通常是 `python`

## 快速开始

```bash
<python-command> scripts/thinkwiki bootstrap
<python-command> scripts/thinkwiki init --root <wiki-root> --title "My Wiki"
<python-command> scripts/thinkwiki ingest --root <wiki-root> --source <file.pdf>
<python-command> scripts/thinkwiki ask --root <wiki-root> --question "AI原生团队的核心定义是什么？"
<python-command> scripts/thinkwiki viewer --root <wiki-root>
<python-command> scripts/thinkwiki graph --root <wiki-root>
```

生成后可直接打开：

- `output/index.html`
- `output/viewer/index.html`
- `output/graph/index.html`

如果你只记一个入口，优先记住：

- `output/index.html`

## 常见任务

### 导入文件或网页

```bash
<python-command> scripts/thinkwiki ingest --root <wiki-root> --source <source-file>
<python-command> scripts/thinkwiki ingest --root <wiki-root> --url "https://example.com/article"
```

### 只做转换，不入库

```bash
<python-command> scripts/thinkwiki convert --source <source-file> --output-file <output-file>
<python-command> scripts/thinkwiki convert --url "https://example.com/article" --output-file <output-file>
```

### 基于已有知识提问

```bash
<python-command> scripts/thinkwiki ask --root <wiki-root> --question "AI原生团队的核心定义是什么？"
```

### 生成综合页

```bash
<python-command> scripts/thinkwiki digest \
  --root <wiki-root> \
  --title "AI原生团队与组织演化" \
  --source-path wiki/sources/a.md \
  --source-path wiki/sources/b.md
```

### 生成概念页或决策页

```bash
<python-command> scripts/thinkwiki crystallize \
  --root <wiki-root> \
  --kind concept \
  --title "AI原生团队" \
  --source-path wiki/sources/a.md
```

### 生成浏览页和知识图谱

```bash
<python-command> scripts/thinkwiki viewer --root <wiki-root>
<python-command> scripts/thinkwiki graph --root <wiki-root>
```

## 运行依赖

基础依赖：

- `python`
- `venv`

平台说明：

- 当前支持 macOS、Linux 和 Windows
- Windows 可以直接用 `PowerShell` 或 `cmd` 运行，但前提是系统里有可用的 `python`
- macOS / Linux 通常使用 `python3 scripts/thinkwiki ...`
- Windows 通常使用 `python scripts/thinkwiki ...`

运行方式：

- `ThinkWiki` 首次运行会自动创建仓库内的 `.venv`
- 运行库会安装到 `ThinkWiki/.venv`
- 后续命令默认都通过这个本地运行环境执行

核心运行库：

- `markitdown`
- `beautifulsoup4`
- `markdownify`
- `mammoth`
- `pdfminer-six`
- `pdfplumber`
- `openpyxl`
- `pandas`
- `python-pptx`
- `xlrd`

根目录 `requirements.txt` 是运行时自举的正式依赖声明，`bootstrap_runtime.py` 会直接读取它来安装本 skill 所需的 Python 运行库。

`bootstrap` 会尝试安装完整的 Markdown、网页和办公文档转换依赖，并在默认包索引失败后自动回退到可配置镜像或官方 PyPI。

如果你所在环境需要指定镜像，可以设置：

```bash
export THINKWIKI_PIP_INDEX_URL="https://pypi.org/simple"
```

## 推荐使用方式

对 Agent 来说，推荐默认流程是：

1. 确定 wiki 根目录
2. 用 `ingest` 导入资料
3. 用 `ask` 做基于证据的回答
4. 对高价值结果再调用 `query / digest / crystallize`
5. 用 `viewer` 和 `graph` 生成可直接查看的成果页
6. 定期运行 `lint` 和 `doctor`

## 运行体检

建议在首次安装或更换运行环境后执行：

```bash
<python-command> scripts/thinkwiki doctor --repo-root .
```

`doctor` 会输出以下能力状态：

- `Core runtime`
- `Web import`
- `PDF import`
- `DOCX import`
- `XLSX import`
- `XLS import`
- `PPTX import`

如果某一项显示 `missing ...`，说明对应格式尚不可用，需要重新执行 `bootstrap` 或检查包索引或网络环境。

## 版本与发布

版本更新记录见 `CHANGELOG.md`。

升级后建议关注：

- 是否新增输出文件
- 是否有命令行为调整
- 是否需要重新执行 `bootstrap`

## License

MIT
