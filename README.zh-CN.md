[English](README.md) | [中文](README.zh-CN.md)

# pg2ts

从 PostgreSQL 数据库 Schema 生成 TypeScript 类型。零运行时开销，纯类型生成。

## 为什么选 pg2ts？

- **无运行时依赖** —— 类型在构建时生成
- **轻量** —— 单文件，无复杂配置
- **实用** —— 还能生成带正确可选字段的 `Insert` 类型
- **Enum 支持** —— PostgreSQL 枚举变成 TypeScript 联合类型
- **Zod 支持** —— 生成带运行时验证的 Zod Schema
- **Drizzle ORM** —— 生成完整的 Drizzle Schema 和关系
- **JSDoc 注释** —— 将 PostgreSQL COMMENT 保留为 JSDoc
- **Agent 友好** —— JSON 输出方便自动化流水线
- **MCP Server** —— 集成 Claude、Cursor 等 AI 工具
- **Watch 模式** —— Schema 变更时自动重新生成

## 安装

```bash
pip install psycopg2-binary
# 或：pip install psycopg2
```

## 使用

```bash
# 使用连接 URL
./pg2ts.py --url "postgresql://user:pass@localhost:5432/mydb" -o types.ts

# 使用独立参数
./pg2ts.py -H localhost -d mydb -U postgres -o types.ts

# 多个 Schema
./pg2ts.py --url "..." --schemas public,app -o types.ts
```

## 输出示例

给定如下表：

```sql
CREATE TYPE status AS ENUM ('active', 'inactive', 'pending');

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    name TEXT,
    status status DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE users IS 'User account information';
COMMENT ON COLUMN users.id IS 'Primary key';
COMMENT ON COLUMN users.email IS 'User email address';
```

你会得到：

```typescript
// Enum types
export type Status = 'active' | 'inactive' | 'pending';
export const StatusValues = ['active', 'inactive', 'pending'] as const;

/** User account information */
export interface Users {
  /** Primary key */
  id: number;
  /** User email address */
  email: string;
  name?: string;
  status?: Status;  // 使用枚举类型！
  created_at?: string;
}

export type UsersInsert = {
  /** User email address */
  email: string;
  /** Primary key */
  id?: number;
  name?: string;
  status?: Status;
  created_at?: string;
};
```

## 功能

### Enum 支持

PostgreSQL 枚举自动转换为 TypeScript 联合类型：

```sql
CREATE TYPE status AS ENUM ('active', 'inactive', 'pending');
CREATE TYPE priority AS ENUM ('low', 'medium', 'high');
```

生成的 TypeScript：

```typescript
export type Status = 'active' | 'inactive' | 'pending';
export const StatusValues = ['active', 'inactive', 'pending'] as const;

export type Priority = 'low' | 'medium' | 'high';
export const PriorityValues = ['low', 'medium', 'high'] as const;

// 在接口中，列使用枚举类型
export interface Tasks {
  id: number;
  status: Status;      // 不是 string！
  priority: Priority;  // 不是 string！
}
```

配合 `--zod` 标记，枚举还会生成 Zod Schema：

```typescript
export type Status = 'active' | 'inactive' | 'pending';
export const StatusValues = ['active', 'inactive', 'pending'] as const;
export const StatusSchema = z.enum(['active', 'inactive', 'pending']);
```

### Drizzle ORM Schema 生成 (`--drizzle`)

生成完整的 Drizzle ORM Schema 而非普通接口：

```bash
./pg2ts.py --url "..." --drizzle -o schema.ts
```

输出：

```typescript
import { pgTable, pgEnum, serial, text, varchar, integer, timestamp, boolean } from 'drizzle-orm/pg-core';

export const statusEnum = pgEnum('status', ['active', 'inactive', 'pending']);

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  email: varchar('email', { length: 255 }).notNull(),
  name: text('name'),
  status: statusEnum('status').default('active'),
  createdAt: timestamp('created_at').defaultNow(),
});

export const posts = pgTable('posts', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id),
  title: text('title').notNull(),
  published: boolean('published').default(false),
});

export type Users = typeof users.$inferSelect;
export type UsersInsert = typeof users.$inferInsert;
export type Posts = typeof posts.$inferSelect;
export type PostsInsert = typeof posts.$inferInsert;
```

### Zod Schema 生成 (`--zod`)

在 TypeScript 类型旁生成用于运行时验证的 Zod Schema：

```bash
./pg2ts.py --url "..." --zod -o types.ts
```

使用 `--zod-dates` 可对日期/时间戳列生成 `z.coerce.date()` 而非 `z.string()`：

```bash
./pg2ts.py --url "..." --zod --zod-dates -o types.ts
```

### 表元数据 (`--with-metadata`)

生成表元数据导出，用于运行时内省：

```bash
./pg2ts.py --url "..." --with-metadata -o types.ts
```

### JSON 输出 (`--json`)

获取生成类型的机器可读元数据（适用于 CI/CD 和 Agent 流水线）：

```bash
./pg2ts.py --url "..." --json -o types.ts
```

### MCP Server（AI Agent 集成）

pg2ts 内置 MCP Server，可与 Claude、Cursor 等 AI 工具集成。

**配置：**

```bash
pip install fastmcp psycopg2-binary
```

**添加到 Claude Desktop**（`~/.config/claude/claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "pg2ts": {
      "command": "python",
      "args": ["/path/to/pg2ts/mcp_server.py"]
    }
  }
}
```

**可用工具：**

| 工具 | 描述 |
|------|------|
| `pg2ts_generate` | 生成 TypeScript 类型（typescript、zod 或 drizzle 格式） |
| `pg2ts_schema` | 获取数据库 Schema（JSON 格式，所有表/列） |
| `pg2ts_table` | 获取特定表的详细信息 |

### Watch 模式 (`--watch` / `-w`)

数据库 Schema 变更时自动重新生成类型：

```bash
./pg2ts.py --url "..." --watch -o types.ts

# 自定义间隔（默认 5 秒）
./pg2ts.py --url "..." --watch --watch-interval 10 -o types.ts
```

按 Ctrl+C 停止。

## 类型映射

| PostgreSQL | TypeScript | Zod |
|------------|------------|-----|
| integer, bigint, real 等 | number | z.number() |
| varchar, text | string | z.string() |
| uuid | string | z.string().uuid() |
| boolean | boolean | z.boolean() |
| timestamp, date, time | string | z.string()（或 `--zod-dates` 时用 z.coerce.date()） |
| json, jsonb | unknown | z.unknown() |
| bytea | Buffer | z.instanceof(Buffer) |
| 数组 (_type) | type[] | z.array(...) |
| 枚举 | 联合类型 | z.enum() |

## CLI 参考

```
Usage: pg2ts.py [OPTIONS]

连接：
  --url URL                  PostgreSQL 连接 URL
  -H, --host HOST           数据库主机（默认：localhost）
  -p, --port PORT           数据库端口（默认：5432）
  -d, --database DATABASE   数据库名
  -U, --user USER           数据库用户（默认：postgres）
  -W, --password PASSWORD   数据库密码

输出：
  -o, --output FILE         输出文件（默认：stdout）
  --schemas SCHEMAS         逗号分隔的 Schema（默认：public）
  --include-schema          在接口名中包含 Schema 名

功能：
  --json                    输出生成类型的 JSON 元数据
  --with-metadata           生成表元数据导出
  --zod                     生成 Zod Schema 而非普通接口
  --zod-dates               对日期/时间戳类型使用 z.date()（需配合 --zod）
  --drizzle                 生成 Drizzle ORM Schema（与 --zod 互斥）
  -w, --watch               监听 Schema 变更并重新生成
  --watch-interval SECONDS  监听间隔（秒，默认：5）
```

## 许可证

MIT
