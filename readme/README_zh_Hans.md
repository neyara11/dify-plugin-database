## 数据库

**作者：** neyara11  
**版本：** 0.1.0
**类型：** 工具  
**仓库：** [https://github.com/neyara11/dify-plugin-database](https://github.com/neyara11/dify-plugin-database)  
**功能请求：** [issues](https://github.com/neyara11/dify-plugin-database/issues)  

本项目是 [hjlarry/dify-plugin-database](https://github.com/hjlarry/dify-plugin-database) 的分支（原作者未发布许可证文件）：修复了数据库连接泄漏问题，新增 Vertica 支持，合并了社区的 ClickHouse/MyScale 支持与数据库 URI 特殊字符编码修复。原始代码的版权仍归原作者所有，详见 [LICENSE](../LICENSE)。
**FAQ：** [FAQ](FAQ.md)  

### 请注意！
**`sql_execute` 工具可以运行任何 SQL 查询；为了增强安全性，请始终使用只读数据库账户。**

### 描述

一个数据库工具，可以轻松地从现有数据库中查询数据。

您可以获取不同格式的数据，例如 `json`、`csv`、`yaml`、`xlsx`、`html`、`md` 等。还支持使用 URL 获取这些数据。

### 用法

#### 1. 输入用于授权的 databaseURI。目前支持 `mysql`、`postgresql`、`sqlite`、`sqlserver`、`oracle`、`clickhouse`、`vertica`，示例格式如下：
```shell
mysql+pymysql://root:123456@localhost:3306/test
postgresql+psycopg2://postgres:123456@localhost:5432/test
sqlite:///test.db
mssql+pymssql://<username>:<password>@<freetds_name>/?charset=utf8
oracle+oracledb://user:pass@hostname:port[/dbname][?service_name=<service>[&key=value&key=value...]]
clickhouse://default:password@localhost:8123/default
clickhouse+connect://default:password@localhost:8123/mydatabase
vertica://dbadmin:password@localhost:5433/docker
```

**ClickHouse/MyScale 特别说明：**
- 支持 ClickHouse 和 MyScale（基于 ClickHouse 的向量数据库）
- 使用 `clickhouse-connect` Python 驱动
- 默认端口：8123（HTTP）、9000（Native TCP）
- MyScale 是一个兼容 ClickHouse 的向量数据库，支持向量相似性搜索功能

**Vertica 特别说明：**
- 使用 `vertica-python` 纯 Python 驱动（DB-API 2.0 兼容）
- 默认端口：5433
- 系统目录表：`v_catalog.tables`、`v_catalog.columns`、`v_catalog.primary_keys`
- Schema 名称区分大小写，默认 Schema 通常为 `public`

> **注意：** 此插件总是在 Docker 中运行，因此 `localhost` 始终指 Docker 内部网络，请尝试使用 `host.docker.internal` 代替。

#### 2. 使用 `SQL 执行` (SQL Execute) 工具从数据库查询数据。
![sql](./_assets/sql_execute.png)
`输出格式` (OUTPUT FORMAT) 用于指定输出数据的格式。如果未指定，默认格式为 `json`，并将输出在工作流节点的 `json` 变量中。`md` 格式将输出在 `text` 变量中，其他格式将创建文件并输出在 `files` 变量中。

如果您输入了 `数据库 URI` (DB URI) 字段，它将覆盖授权时填写的 URI，因此这在您想在同一工作流中使用不同数据库时非常有用。

#### 3. 使用 `文本转 SQL` (Text to SQL) 工具可以将用户输入转换为有效的 SQL 查询。
![text](./_assets/text.png)

该工具将使用[此处](https://github.com/hjlarry/dify-plugin-database/blob/d6dd3695840e8eb5d673611784af148b1789da97/tools/text2sql.py#L9)的默认提示词（prompt）来生成 SQL 查询。如果您指定了 `表` (TABLES) 字段，它将仅将这些表的结构（schema）获取到 LLM 上下文中。

#### 4. 使用 `获取表模式` (Get Table Schema) 工具可以获取表的结构（schema）。

如果 `文本转 SQL` 工具无法生成有用的 SQL 查询，您可以使用此工具获取表的结构(在text字段中返回)，然后将该结构与您自己的提示词或其他信息结合，输入到 LLM 节点以生成有用的 SQL 查询。

#### 5. `CSV 查询` (CSV Query) 工具可以对 CSV 文件执行 SQL 查询。
![csv](./_assets/csv.png)
表名始终为 `csv`，列名是 CSV 文件的第一行。它支持输出 `json` 和 `md` 格式。

#### 6. 使用 `端点` (endpoint) 工具通过 URL 请求获取数据。

URL 请求格式示例：
```shell
curl -X POST 'https://daemon-plugin.dify.dev/o3wvwZfYFLU5iGopr5CxYmGaM5mWV7xf/sql' -H 'Content-Type: application/json' -d '{"query":"select * from test", "format": "md"}'
```

### 更新日志

#### 0.0.8
1. 新增 Vertica 数据库支持
2. 使用 vertica-python 1.4.0+ 纯 Python 驱动（DB-API 2.0）
3. 支持所有现有的输出格式（JSON、CSV、YAML、XLSX、HTML、Markdown）
4. 支持通过 v_catalog 系统表获取表结构
5. 支持 text2sql Vertica 方言

#### 0.0.7
1. 新增 ClickHouse/MyScale 数据库支持
2. 使用 clickhouse-connect 0.10.0+ 驱动
3. 支持所有现有的输出格式（JSON、CSV、YAML、XLSX、HTML、Markdown）
4. 支持表结构获取，包括 ClickHouse 特有的引擎、排序键、分区键等信息
5. 完全兼容 MyScale 向量数据库

#### 0.0.6
1. 支持在 `get table schema` 工具中获取更多信息，例如表和字段的注释、外键关联索引等
2. support special `schema` of `get table schema` tool

#### 0.0.5
1. 支持 SQL 查询中的 `with` 语句
2. 修复 `text2sql` 生成带双引号的 SQL 字符串的问题
3. 修复 `too many clients already` (客户端连接过多) 的问题
4. 添加 SQLAlchemy 的连接选项
5. 将授权中的 `db_uri` 更改为可选字段
6. 添加 `获取表模式` (Get Table Schema) 工具以直接响应表的模式
7. 添加 `CSV 查询` (CSV Query) 工具以对 CSV 文件执行 SQL 查询

#### 0.0.4
1. 支持 `sqlserver`、`oracle` 连接
2. 将 `db_url` 更改为 LLM 格式，以便用户可以使用工作流的环境变量来设置数据库 URI
3. 修复在 Agent 应用中，`sql_execute` 工具仅响应第一个结果的问题
4. 将 `text2sql` 工具的表模式信息迁移到用户提示词中，以防止系统提示词过长导致无响应

#### 0.0.3
1. 在 requirements.txt 中添加 `cryptography` 以支持 MySQL 8.1 的 sha256 连接
2. 移除端点（endpoint）的数据库 URI 设置
3. 添加 `db_uri` 以支持连接到多个数据库
4. 将 `sql_execute` 工具的 `output` 更改为表单（form）格式
5. 将 `text2sql` 工具的 `tables` 更改为 LLM 格式
6. 修复 SQL 查询被转换为小写的问题 [issue](https://github.com/hjlarry/dify-plugin-database/issues/2)



### 已知限制

- Dify 1.16 的 Agent 节点不会保存 `text2sql` 的 `model-selector` 参数（Dify 前端问题；Workflow 节点正常）：请在 Workflow 中使用 `text2sql`，或在 Agent 中改用 `sql_execute`。
- 不支持 Oracle 12.1 以下版本（python-oracledb thin 模式要求 12.1+）。
- 每次调用只支持一条 SQL 语句，不支持多结果集。
- 没有单条查询超时限制，受 Dify 插件执行超时约束。
- `sqlite:///relative.db` 相对于插件工作目录解析，建议使用绝对路径。
- JSON 输出中的 `NaN`/`Infinity` 返回为空字符串。

### 支持

问题和 bug 反馈: https://github.com/neyara11/dify-plugin-database/issues
