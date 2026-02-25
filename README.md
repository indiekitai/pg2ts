# pg2ts

Generate TypeScript types from your PostgreSQL database schema. Zero runtime overhead, just pure type generation.

## Why?

- **No runtime dependencies** — Types are generated at build time
- **Lightweight** — Single file, no complex setup
- **Practical** — Also generates `Insert` types with proper optional fields
- **Enum Support** — PostgreSQL enums become TypeScript union types
- **Zod Support** — Generate runtime-validated Zod schemas
- **Drizzle ORM** — Generate complete Drizzle schema with relations
- **JSDoc Comments** — Preserves PostgreSQL COMMENT as JSDoc
- **Agent-Friendly** — JSON output for automation pipelines
- **MCP Server** — AI agent integration for Claude, Cursor, etc.
- **Watch Mode** — Auto-regenerate on schema changes

## Install

```bash
pip install psycopg2-binary
# or: pip install psycopg2
```

## Usage

```bash
# Using connection URL
./pg2ts.py --url "postgresql://user:pass@localhost:5432/mydb" -o types.ts

# Using individual params
./pg2ts.py -H localhost -d mydb -U postgres -o types.ts

# Multiple schemas
./pg2ts.py --url "..." --schemas public,app -o types.ts
```

## Output Example

Given this table:

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

You get:

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
  status?: Status;  // Uses the enum type!
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

## Features

### Enum Support

PostgreSQL enums are automatically converted to TypeScript union types:

```sql
CREATE TYPE status AS ENUM ('active', 'inactive', 'pending');
CREATE TYPE priority AS ENUM ('low', 'medium', 'high');
```

Generated TypeScript:

```typescript
// Enum types
export type Status = 'active' | 'inactive' | 'pending';
export const StatusValues = ['active', 'inactive', 'pending'] as const;

export type Priority = 'low' | 'medium' | 'high';
export const PriorityValues = ['low', 'medium', 'high'] as const;

// In interfaces, columns use the enum type
export interface Tasks {
  id: number;
  status: Status;      // Not string!
  priority: Priority;  // Not string!
}
```

With `--zod` flag, enums also get Zod schemas:

```typescript
export type Status = 'active' | 'inactive' | 'pending';
export const StatusValues = ['active', 'inactive', 'pending'] as const;
export const StatusSchema = z.enum(['active', 'inactive', 'pending']);
```

### Drizzle ORM Schema Generation (`--drizzle`)

Generate a complete Drizzle ORM schema instead of plain interfaces:

```bash
./pg2ts.py --url "..." --drizzle -o schema.ts
```

Output:

```typescript
import { pgTable, pgEnum, serial, text, varchar, integer, timestamp, boolean } from 'drizzle-orm/pg-core';

// Enums
export const statusEnum = pgEnum('status', ['active', 'inactive', 'pending']);

// Tables
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

// Inferred types
export type Users = typeof users.$inferSelect;
export type UsersInsert = typeof users.$inferInsert;
export type Posts = typeof posts.$inferSelect;
export type PostsInsert = typeof posts.$inferInsert;
```

**Drizzle type mapping:**

| PostgreSQL | Drizzle |
|------------|---------|
| serial | serial() |
| integer, int4 | integer() |
| bigint, int8 | bigint({ mode: 'number' }) |
| varchar(n) | varchar('col', { length: n }) |
| text | text() |
| boolean | boolean() |
| timestamp, timestamptz | timestamp() |
| date | date() |
| json | json() |
| jsonb | jsonb() |
| uuid | uuid() |
| numeric(p,s) | numeric({ precision: p, scale: s }) |

**Drizzle features:**
- Primary keys → `.primaryKey()`
- NOT NULL → `.notNull()`
- DEFAULT values → `.default()` / `.defaultNow()` / `.defaultRandom()`
- Foreign keys → `.references(() => table.column)`
- Enums → `pgEnum()` definitions

### Zod Schema Generation (`--zod`)

Generate Zod schemas for runtime validation alongside TypeScript types:

```bash
./pg2ts.py --url "..." --zod -o types.ts
```

Output:

```typescript
import { z } from 'zod';

// Enum types
export type Status = 'active' | 'inactive' | 'pending';
export const StatusValues = ['active', 'inactive', 'pending'] as const;
export const StatusSchema = z.enum(['active', 'inactive', 'pending']);

/** User account information */
export const UsersSchema = z.object({
  /** Primary key */
  id: z.number(),
  /** User email address */
  email: z.string(),
  name: z.string().nullable(),
  status: StatusSchema.nullable(),
  created_at: z.string().nullable(),
});

export type Users = z.infer<typeof UsersSchema>;

export const UsersInsertSchema = z.object({
  /** User email address */
  email: z.string(),
  /** Primary key */
  id: z.number().optional(),
  name: z.string().nullable().optional(),
  status: StatusSchema.nullable().optional(),
  created_at: z.string().nullable().optional(),
});

export type UsersInsert = z.infer<typeof UsersInsertSchema>;
```

Use `--zod-dates` to generate `z.coerce.date()` instead of `z.string()` for date/timestamp columns:

```bash
./pg2ts.py --url "..." --zod --zod-dates -o types.ts
```

### Table Metadata (`--with-metadata`)

Generate table metadata exports for runtime introspection:

```bash
./pg2ts.py --url "..." --with-metadata -o types.ts
```

Output:

```typescript
export const usersTable = {
  tableName: 'users',
  columns: ['id', 'email', 'name', 'status', 'created_at'] as const,
  requiredForInsert: ['email'] as const,
} as const;

export const tables = {
  users: usersTable,
} as const;
```

### JSON Output (`--json`)

Get machine-readable metadata about generated types (useful for CI/CD and agent pipelines):

```bash
./pg2ts.py --url "..." --json -o types.ts
```

Output:

```json
{
  "tables": [
    {
      "name": "users",
      "schema": "public",
      "columns": ["id", "email", "name", "status", "created_at"],
      "required": ["email"],
      "optional": ["id", "name", "status", "created_at"],
      "comment": "User account information"
    }
  ],
  "enums": [
    {"name": "status", "values": ["active", "inactive", "pending"]}
  ],
  "enums_count": 1,
  "types_generated": 2,
  "output_file": "types.ts"
}
```

### MCP Server (for AI Agents)

pg2ts includes an MCP server for integration with Claude, Cursor, and other AI tools.

**Setup:**

```bash
pip install fastmcp psycopg2-binary
```

**Add to Claude Desktop** (`~/.config/claude/claude_desktop_config.json`):

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

**Available Tools:**

| Tool | Description |
|------|-------------|
| `pg2ts_generate` | Generate TypeScript types (typescript, zod, or drizzle format) |
| `pg2ts_schema` | Get database schema as JSON (all tables/columns) |
| `pg2ts_table` | Get detailed info about a specific table |

**Example Usage:**

```
> What tables are in my database?
[uses pg2ts_schema]

> Generate TypeScript types for my database
[uses pg2ts_generate, returns .ts content]

> Show me the users table structure
[uses pg2ts_table with table="users"]
```

**Direct Python Usage:**

```python
from mcp_server import pg2ts_generate, pg2ts_schema, pg2ts_table

# Get all tables as JSON
schema = pg2ts_schema("postgresql://user:pass@host:5432/db")

# Generate TypeScript
ts_code = pg2ts_generate("postgresql://...", format="typescript")

# Get specific table
users = pg2ts_table("postgresql://...", table="users")
```

### Watch Mode (`--watch` / `-w`)

Automatically regenerate types when database schema changes:

```bash
./pg2ts.py --url "..." --watch -o types.ts

# Custom interval (default: 5 seconds)
./pg2ts.py --url "..." --watch --watch-interval 10 -o types.ts
```

Press Ctrl+C to stop watching.

### JSDoc Comments from PostgreSQL

PostgreSQL `COMMENT` statements are automatically converted to JSDoc comments:

```sql
COMMENT ON TABLE users IS 'User account information';
COMMENT ON COLUMN users.email IS 'User email address';
```

This works automatically with all output modes (interfaces, Zod, Drizzle, metadata).

## Type Mapping

| PostgreSQL | TypeScript | Zod |
|------------|------------|-----|
| integer, bigint, real, etc. | number | z.number() |
| varchar, text | string | z.string() |
| uuid | string | z.string().uuid() |
| boolean | boolean | z.boolean() |
| timestamp, date, time | string | z.string() (or z.coerce.date() with --zod-dates) |
| json, jsonb | unknown | z.unknown() |
| bytea | Buffer | z.instanceof(Buffer) |
| Arrays (_type) | type[] | z.array(...) |
| Enums | union type | z.enum() |

## CLI Reference

```
Usage: pg2ts.py [OPTIONS]

Connection:
  --url URL                  PostgreSQL connection URL
  -H, --host HOST           Database host (default: localhost)
  -p, --port PORT           Database port (default: 5432)
  -d, --database DATABASE   Database name
  -U, --user USER           Database user (default: postgres)
  -W, --password PASSWORD   Database password

Output:
  -o, --output FILE         Output file (default: stdout)
  --schemas SCHEMAS         Comma-separated schemas (default: public)
  --include-schema          Include schema name in interface names

Features:
  --json                    Output JSON metadata about generated types
  --with-metadata           Generate table metadata exports
  --zod                     Generate Zod schemas instead of plain interfaces
  --zod-dates               Use z.date() for date/timestamp types (requires --zod)
  --drizzle                 Generate Drizzle ORM schema (mutually exclusive with --zod)
  -w, --watch               Watch for schema changes and regenerate
  --watch-interval SECONDS  Watch interval in seconds (default: 5)
```

## Examples

```bash
# Basic usage
./pg2ts.py --url "postgresql://user:pass@localhost/mydb" -o types.ts

# Generate Drizzle ORM schema
./pg2ts.py --url "..." --drizzle -o schema.ts

# Generate Zod schemas with date coercion
./pg2ts.py --url "..." --zod --zod-dates -o schema.ts

# Generate with metadata for ORM-like usage
./pg2ts.py --url "..." --with-metadata -o types.ts

# CI/CD: Generate and get JSON report
./pg2ts.py --url "..." --json -o types.ts > report.json

# Development: Watch for changes
./pg2ts.py --url "..." --watch --watch-interval 3 -o types.ts

# All features combined (except drizzle)
./pg2ts.py --url "..." --zod --with-metadata --json -o types.ts
```

## License

MIT
