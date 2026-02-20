# pg2ts

Generate TypeScript types from your PostgreSQL database schema. Zero runtime overhead, just pure type generation.

## Why?

- **No runtime dependencies** — Types are generated at build time
- **Lightweight** — Single file, no complex setup
- **Practical** — Also generates `Insert` types with proper optional fields
- **Zod Support** — Generate runtime-validated Zod schemas
- **JSDoc Comments** — Preserves PostgreSQL COMMENT as JSDoc
- **Agent-Friendly** — JSON output for automation pipelines
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
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE users IS 'User account information';
COMMENT ON COLUMN users.id IS 'Primary key';
COMMENT ON COLUMN users.email IS 'User email address';
```

You get:

```typescript
/** User account information */
export interface Users {
  /** Primary key */
  id: number;
  /** User email address */
  email: string;
  name?: string;
  created_at?: string;
}

export type UsersInsert = {
  /** User email address */
  email: string;
  /** Primary key */
  id?: number;
  name?: string;
  created_at?: string;
};
```

## Features

### Zod Schema Generation (`--zod`)

Generate Zod schemas for runtime validation alongside TypeScript types:

```bash
./pg2ts.py --url "..." --zod -o types.ts
```

Output:

```typescript
import { z } from 'zod';

/** User account information */
export const UsersSchema = z.object({
  /** Primary key */
  id: z.number(),
  /** User email address */
  email: z.string(),
  name: z.string().nullable(),
  created_at: z.string().nullable(),
});

export type Users = z.infer<typeof UsersSchema>;

export const UsersInsertSchema = z.object({
  /** User email address */
  email: z.string(),
  /** Primary key */
  id: z.number().optional(),
  name: z.string().nullable().optional(),
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
  columns: ['id', 'email', 'name', 'created_at'] as const,
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
      "columns": ["id", "email", "name", "created_at"],
      "required": ["email"],
      "optional": ["id", "name", "created_at"],
      "comment": "User account information"
    }
  ],
  "types_generated": 2,
  "output_file": "types.ts"
}
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

This works automatically with all output modes (interfaces, Zod, metadata).

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
  -w, --watch               Watch for schema changes and regenerate
  --watch-interval SECONDS  Watch interval in seconds (default: 5)
```

## Examples

```bash
# Basic usage
./pg2ts.py --url "postgresql://user:pass@localhost/mydb" -o types.ts

# Generate Zod schemas with date coercion
./pg2ts.py --url "..." --zod --zod-dates -o schema.ts

# Generate with metadata for ORM-like usage
./pg2ts.py --url "..." --with-metadata -o types.ts

# CI/CD: Generate and get JSON report
./pg2ts.py --url "..." --json -o types.ts > report.json

# Development: Watch for changes
./pg2ts.py --url "..." --watch --watch-interval 3 -o types.ts

# All features combined
./pg2ts.py --url "..." --zod --with-metadata --json -o types.ts
```

## License

MIT
