# pg2ts

Generate TypeScript types from your PostgreSQL database schema. Zero runtime overhead, just pure type generation.

## Why?

- **No runtime dependencies** — Types are generated at build time
- **Lightweight** — Single file, no complex setup
- **Practical** — Also generates `Insert` types with proper optional fields

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
```

You get:

```typescript
export interface Users {
  id: number;
  email: string;
  name?: string;
  created_at?: string;
}

export type UsersInsert = {
  email: string;
  id?: number;
  name?: string;
  created_at?: string;
};
```

## Type Mapping

| PostgreSQL | TypeScript |
|------------|------------|
| integer, bigint, real, etc. | number |
| varchar, text, uuid | string |
| boolean | boolean |
| timestamp, date, time | string |
| json, jsonb | unknown |
| bytea | Buffer |
| Arrays (_type) | type[] |

## License

MIT
