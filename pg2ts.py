#!/usr/bin/env python3
"""
pg2ts - Generate TypeScript types from PostgreSQL schemas

A lightweight CLI tool to sync your database schema with TypeScript interfaces.
No runtime dependencies, just pure type generation.

Usage:
    pg2ts --host localhost --db mydb --user postgres --output types.ts
    pg2ts --url "postgresql://user:pass@host:5432/db" --output types.ts
"""

import argparse
import json
import sys
import time
import hashlib
from typing import Optional
from dataclasses import dataclass, field
from urllib.parse import urlparse

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("Error: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


# PostgreSQL to TypeScript type mapping
PG_TO_TS = {
    # Numeric types
    "smallint": "number",
    "integer": "number",
    "bigint": "number",
    "int2": "number",
    "int4": "number",
    "int8": "number",
    "decimal": "number",
    "numeric": "number",
    "real": "number",
    "double precision": "number",
    "float4": "number",
    "float8": "number",
    "serial": "number",
    "bigserial": "number",
    "smallserial": "number",
    
    # Boolean
    "boolean": "boolean",
    "bool": "boolean",
    
    # String types
    "character varying": "string",
    "varchar": "string",
    "character": "string",
    "char": "string",
    "text": "string",
    "citext": "string",
    "uuid": "string",
    "name": "string",
    
    # Date/Time
    "timestamp": "string",
    "timestamp without time zone": "string",
    "timestamp with time zone": "string",
    "timestamptz": "string",
    "date": "string",
    "time": "string",
    "time without time zone": "string",
    "time with time zone": "string",
    "timetz": "string",
    "interval": "string",
    
    # JSON
    "json": "unknown",
    "jsonb": "unknown",
    
    # Binary
    "bytea": "Buffer",
    
    # Network
    "inet": "string",
    "cidr": "string",
    "macaddr": "string",
    
    # Arrays will be handled specially
}

# PostgreSQL to Zod type mapping
PG_TO_ZOD = {
    # Numeric types
    "smallint": "z.number()",
    "integer": "z.number()",
    "bigint": "z.number()",
    "int2": "z.number()",
    "int4": "z.number()",
    "int8": "z.number()",
    "decimal": "z.number()",
    "numeric": "z.number()",
    "real": "z.number()",
    "double precision": "z.number()",
    "float4": "z.number()",
    "float8": "z.number()",
    "serial": "z.number()",
    "bigserial": "z.number()",
    "smallserial": "z.number()",
    
    # Boolean
    "boolean": "z.boolean()",
    "bool": "z.boolean()",
    
    # String types
    "character varying": "z.string()",
    "varchar": "z.string()",
    "character": "z.string()",
    "char": "z.string()",
    "text": "z.string()",
    "citext": "z.string()",
    "uuid": "z.string().uuid()",
    "name": "z.string()",
    
    # Date/Time - default to string, can switch to z.date() with --zod-dates
    "timestamp": "z.string()",
    "timestamp without time zone": "z.string()",
    "timestamp with time zone": "z.string()",
    "timestamptz": "z.string()",
    "date": "z.string()",
    "time": "z.string()",
    "time without time zone": "z.string()",
    "time with time zone": "z.string()",
    "timetz": "z.string()",
    "interval": "z.string()",
    
    # JSON
    "json": "z.unknown()",
    "jsonb": "z.unknown()",
    
    # Binary
    "bytea": "z.instanceof(Buffer)",
    
    # Network
    "inet": "z.string()",
    "cidr": "z.string()",
    "macaddr": "z.string()",
}

# Date types that should use z.date() when --zod-dates is enabled
DATE_TYPES = {
    "timestamp", "timestamp without time zone", "timestamp with time zone",
    "timestamptz", "date"
}


@dataclass
class Column:
    name: str
    data_type: str
    is_nullable: bool
    column_default: Optional[str]
    is_array: bool = False
    comment: Optional[str] = None


@dataclass
class Table:
    schema: str
    name: str
    columns: list[Column]
    comment: Optional[str] = None


def snake_to_pascal(name: str) -> str:
    """Convert snake_case to PascalCase."""
    return "".join(word.capitalize() for word in name.split("_"))


def snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


def get_ts_type(pg_type: str, is_array: bool = False) -> str:
    """Convert PostgreSQL type to TypeScript type."""
    # Handle array types
    if pg_type.startswith("_"):
        pg_type = pg_type[1:]
        is_array = True
    
    # Handle ARRAY suffix
    if pg_type.endswith("[]"):
        pg_type = pg_type[:-2]
        is_array = True
    
    ts_type = PG_TO_TS.get(pg_type.lower(), "unknown")
    
    if is_array:
        return f"{ts_type}[]"
    return ts_type


def get_zod_type(pg_type: str, is_array: bool = False, use_dates: bool = False) -> str:
    """Convert PostgreSQL type to Zod type."""
    # Handle array types
    if pg_type.startswith("_"):
        pg_type = pg_type[1:]
        is_array = True
    
    # Handle ARRAY suffix
    if pg_type.endswith("[]"):
        pg_type = pg_type[:-2]
        is_array = True
    
    # Check for date types when --zod-dates is enabled
    if use_dates and pg_type.lower() in DATE_TYPES:
        zod_type = "z.coerce.date()"
    else:
        zod_type = PG_TO_ZOD.get(pg_type.lower(), "z.unknown()")
    
    if is_array:
        return f"z.array({zod_type})"
    return zod_type


def fetch_comments(conn, schema: str, table_name: str) -> tuple[Optional[str], dict[str, str]]:
    """Fetch table and column comments from PostgreSQL."""
    table_comment = None
    column_comments = {}
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get table comment
        cur.execute("""
            SELECT obj_description(c.oid) as table_comment
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = %s AND n.nspname = %s
        """, (table_name, schema))
        row = cur.fetchone()
        if row and row["table_comment"]:
            table_comment = row["table_comment"]
        
        # Get column comments
        cur.execute("""
            SELECT a.attname as column_name,
                   col_description(c.oid, a.attnum) as column_comment
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid
            WHERE c.relname = %s 
              AND n.nspname = %s
              AND a.attnum > 0
              AND NOT a.attisdropped
        """, (table_name, schema))
        for row in cur.fetchall():
            if row["column_comment"]:
                column_comments[row["column_name"]] = row["column_comment"]
    
    return table_comment, column_comments


def fetch_tables(conn, schemas: list[str], fetch_comments_flag: bool = False) -> list[Table]:
    """Fetch all tables and their columns from the database."""
    tables = []
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get all tables
        cur.execute("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema = ANY(%s)
            ORDER BY table_schema, table_name
        """, (schemas,))
        
        table_rows = cur.fetchall()
        
        for row in table_rows:
            schema = row["table_schema"]
            table_name = row["table_name"]
            
            # Fetch comments if requested
            table_comment = None
            column_comments = {}
            if fetch_comments_flag:
                table_comment, column_comments = fetch_comments(conn, schema, table_name)
            
            # Get columns for this table
            cur.execute("""
                SELECT 
                    column_name,
                    data_type,
                    udt_name,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema, table_name))
            
            columns = []
            for col in cur.fetchall():
                # Use udt_name for better type detection (handles arrays)
                data_type = col["udt_name"]
                is_array = data_type.startswith("_")
                
                columns.append(Column(
                    name=col["column_name"],
                    data_type=data_type,
                    is_nullable=col["is_nullable"] == "YES",
                    column_default=col["column_default"],
                    is_array=is_array,
                    comment=column_comments.get(col["column_name"])
                ))
            
            tables.append(Table(
                schema=schema,
                name=table_name,
                columns=columns,
                comment=table_comment
            ))
    
    return tables


def get_schema_hash(conn, schemas: list[str]) -> str:
    """Get a hash of the current schema for change detection."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = ANY(%s)
            ORDER BY table_schema, table_name, ordinal_position
        """, (schemas,))
        rows = cur.fetchall()
        schema_str = json.dumps([dict(r) for r in rows], sort_keys=True)
        return hashlib.md5(schema_str.encode()).hexdigest()


def generate_typescript(
    tables: list[Table], 
    include_schema: bool = False,
    with_metadata: bool = False,
    zod: bool = False,
    zod_dates: bool = False
) -> str:
    """Generate TypeScript interfaces from tables."""
    lines = [
        "// Auto-generated by pg2ts",
        "// https://github.com/indiekitai/pg2ts",
        "// Do not edit manually!",
        "",
    ]
    
    # Add Zod import if needed
    if zod:
        lines.append("import { z } from 'zod';")
        lines.append("")
    
    for table in tables:
        # Interface name
        if include_schema and table.schema != "public":
            interface_name = f"{snake_to_pascal(table.schema)}{snake_to_pascal(table.name)}"
        else:
            interface_name = snake_to_pascal(table.name)
        
        # Table JSDoc comment
        if table.comment:
            lines.append(f"/** {table.comment} */")
        
        if zod:
            # Generate Zod schema for select (all fields)
            lines.append(f"export const {interface_name}Schema = z.object({{")
            for col in table.columns:
                zod_type = get_zod_type(col.data_type, col.is_array, zod_dates)
                
                # Column JSDoc comment
                if col.comment:
                    lines.append(f"  /** {col.comment} */")
                
                if col.is_nullable:
                    lines.append(f"  {col.name}: {zod_type}.nullable(),")
                else:
                    lines.append(f"  {col.name}: {zod_type},")
            lines.append("});")
            lines.append("")
            
            # Generate type from schema
            lines.append(f"export type {interface_name} = z.infer<typeof {interface_name}Schema>;")
            lines.append("")
            
            # Generate Insert schema
            required_cols = [c for c in table.columns if not c.is_nullable and c.column_default is None]
            optional_cols = [c for c in table.columns if c.is_nullable or c.column_default is not None]
            
            lines.append(f"export const {interface_name}InsertSchema = z.object({{")
            for col in required_cols:
                zod_type = get_zod_type(col.data_type, col.is_array, zod_dates)
                if col.comment:
                    lines.append(f"  /** {col.comment} */")
                lines.append(f"  {col.name}: {zod_type},")
            for col in optional_cols:
                zod_type = get_zod_type(col.data_type, col.is_array, zod_dates)
                if col.comment:
                    lines.append(f"  /** {col.comment} */")
                if col.is_nullable:
                    lines.append(f"  {col.name}: {zod_type}.nullable().optional(),")
                else:
                    lines.append(f"  {col.name}: {zod_type}.optional(),")
            lines.append("});")
            lines.append("")
            
            lines.append(f"export type {interface_name}Insert = z.infer<typeof {interface_name}InsertSchema>;")
            lines.append("")
        else:
            # Generate standard TypeScript interface
            lines.append(f"export interface {interface_name} {{")
            
            for col in table.columns:
                ts_type = get_ts_type(col.data_type, col.is_array)
                optional = "?" if col.is_nullable else ""
                
                # Column JSDoc comment
                if col.comment:
                    lines.append(f"  /** {col.comment} */")
                elif ts_type == "unknown":
                    lines.append(f"  /** PostgreSQL type: {col.data_type} */")
                
                lines.append(f"  {col.name}{optional}: {ts_type};")
            
            lines.append("}")
            lines.append("")
    
    # Add helper types (only for non-zod mode, zod mode already has Insert types)
    if not zod:
        lines.extend([
            "// Helper types for insert/update operations",
            "",
        ])
        
        for table in tables:
            if include_schema and table.schema != "public":
                interface_name = f"{snake_to_pascal(table.schema)}{snake_to_pascal(table.name)}"
            else:
                interface_name = snake_to_pascal(table.name)
            
            # Generate Insert type (required fields only)
            required_cols = [c for c in table.columns if not c.is_nullable and c.column_default is None]
            optional_cols = [c for c in table.columns if c.is_nullable or c.column_default is not None]
            
            if required_cols or optional_cols:
                lines.append(f"export type {interface_name}Insert = {{")
                for col in required_cols:
                    ts_type = get_ts_type(col.data_type, col.is_array)
                    if col.comment:
                        lines.append(f"  /** {col.comment} */")
                    lines.append(f"  {col.name}: {ts_type};")
                for col in optional_cols:
                    ts_type = get_ts_type(col.data_type, col.is_array)
                    if col.comment:
                        lines.append(f"  /** {col.comment} */")
                    lines.append(f"  {col.name}?: {ts_type};")
                lines.append("};")
                lines.append("")
    
    # Generate table metadata if requested
    if with_metadata:
        lines.append("// Table metadata")
        lines.append("")
        
        for table in tables:
            if include_schema and table.schema != "public":
                interface_name = f"{snake_to_pascal(table.schema)}{snake_to_pascal(table.name)}"
                var_name = f"{snake_to_camel(table.schema)}{snake_to_pascal(table.name)}Table"
            else:
                interface_name = snake_to_pascal(table.name)
                var_name = f"{snake_to_camel(table.name)}Table"
            
            column_names = [col.name for col in table.columns]
            required_cols = [c.name for c in table.columns if not c.is_nullable and c.column_default is None]
            
            lines.append(f"export const {var_name} = {{")
            lines.append(f"  tableName: '{table.name}',")
            lines.append(f"  columns: {json.dumps(column_names)} as const,")
            lines.append(f"  requiredForInsert: {json.dumps(required_cols)} as const,")
            lines.append("} as const;")
            lines.append("")
        
        # Generate tables object
        lines.append("export const tables = {")
        for table in tables:
            if include_schema and table.schema != "public":
                var_name = f"{snake_to_camel(table.schema)}{snake_to_pascal(table.name)}Table"
            else:
                var_name = f"{snake_to_camel(table.name)}Table"
            lines.append(f"  {table.name}: {var_name},")
        lines.append("} as const;")
        lines.append("")
    
    return "\n".join(lines)


def generate_json_metadata(tables: list[Table], output_file: Optional[str], zod: bool = False) -> dict:
    """Generate JSON metadata for agent-friendly output."""
    table_data = []
    types_count = 0
    
    for table in tables:
        required_cols = [c.name for c in table.columns if not c.is_nullable and c.column_default is None]
        optional_cols = [c.name for c in table.columns if c.is_nullable or c.column_default is not None]
        
        table_data.append({
            "name": table.name,
            "schema": table.schema,
            "columns": [col.name for col in table.columns],
            "required": required_cols,
            "optional": optional_cols,
            "comment": table.comment
        })
        
        # Count types: Interface + InsertType (+ 2 more for Zod schemas)
        types_count += 4 if zod else 2
    
    return {
        "tables": table_data,
        "types_generated": types_count,
        "output_file": output_file or "stdout"
    }


def parse_connection_url(url: str) -> dict:
    """Parse PostgreSQL connection URL."""
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/") or "postgres",
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
    }


def run_generation(args, conn_params: dict, schemas: list[str]) -> tuple[str, dict]:
    """Run the type generation and return output + metadata."""
    conn = psycopg2.connect(**conn_params)
    
    # Fetch comments if any output mode needs them (always fetch for JSDoc)
    fetch_comments_flag = True
    
    tables = fetch_tables(conn, schemas, fetch_comments_flag)
    conn.close()
    
    if not tables:
        raise ValueError("No tables found in specified schemas.")
    
    # Generate TypeScript
    output = generate_typescript(
        tables, 
        args.include_schema,
        args.with_metadata,
        args.zod,
        args.zod_dates
    )
    
    # Generate JSON metadata
    metadata = generate_json_metadata(tables, args.output, args.zod)
    
    return output, metadata


def watch_loop(args, conn_params: dict, schemas: list[str], interval: int):
    """Watch for schema changes and regenerate types."""
    print(f"👀 Watching for schema changes (interval: {interval}s)...")
    print("   Press Ctrl+C to stop")
    print("")
    
    last_hash = None
    
    try:
        while True:
            try:
                conn = psycopg2.connect(**conn_params)
                current_hash = get_schema_hash(conn, schemas)
                conn.close()
                
                if last_hash is None:
                    # First run
                    output, metadata = run_generation(args, conn_params, schemas)
                    write_output(output, args.output, metadata, args.json)
                    last_hash = current_hash
                    print(f"✓ Initial generation complete: {len(metadata['tables'])} tables")
                elif current_hash != last_hash:
                    # Schema changed
                    output, metadata = run_generation(args, conn_params, schemas)
                    write_output(output, args.output, metadata, args.json)
                    last_hash = current_hash
                    print(f"✓ Schema change detected, regenerated: {len(metadata['tables'])} tables")
                
            except psycopg2.Error as e:
                print(f"⚠ Database connection error: {e}", file=sys.stderr)
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n👋 Watch mode stopped")


def write_output(output: str, output_file: Optional[str], metadata: dict, json_output: bool):
    """Write the generated output to file or stdout."""
    if output_file:
        with open(output_file, "w") as f:
            f.write(output)
        if json_output:
            print(json.dumps(metadata, indent=2))
        else:
            print(f"✓ Generated {len(metadata['tables'])} interfaces → {output_file}")
    else:
        if json_output:
            # When JSON mode + stdout, we can't print both TS and JSON
            # So we print just the JSON metadata
            print(json.dumps(metadata, indent=2))
        else:
            print(output)


def main():
    parser = argparse.ArgumentParser(
        description="Generate TypeScript types from PostgreSQL schemas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pg2ts --url "postgresql://user:pass@localhost:5432/mydb" -o types.ts
  pg2ts -H localhost -d mydb -U postgres -o types.ts
  pg2ts --url "..." --schemas public,app -o types.ts
  pg2ts --url "..." --zod -o types.ts              # Generate Zod schemas
  pg2ts --url "..." --with-metadata -o types.ts    # Include table metadata
  pg2ts --url "..." --json -o types.ts             # Output JSON metadata
  pg2ts --url "..." --watch -o types.ts            # Watch for changes
        """,
    )
    
    # Connection options
    conn_group = parser.add_argument_group("Connection")
    conn_group.add_argument("--url", help="PostgreSQL connection URL")
    conn_group.add_argument("-H", "--host", default="localhost", help="Database host")
    conn_group.add_argument("-p", "--port", type=int, default=5432, help="Database port")
    conn_group.add_argument("-d", "--database", help="Database name")
    conn_group.add_argument("-U", "--user", default="postgres", help="Database user")
    conn_group.add_argument("-W", "--password", default="", help="Database password")
    
    # Output options
    output_group = parser.add_argument_group("Output")
    output_group.add_argument("-o", "--output", help="Output file (default: stdout)")
    output_group.add_argument("--schemas", default="public", help="Comma-separated schemas (default: public)")
    output_group.add_argument("--include-schema", action="store_true", help="Include schema name in interface names")
    
    # New feature flags
    feature_group = parser.add_argument_group("Features")
    feature_group.add_argument("--json", action="store_true", help="Output JSON metadata about generated types")
    feature_group.add_argument("--with-metadata", action="store_true", help="Generate table metadata exports")
    feature_group.add_argument("--zod", action="store_true", help="Generate Zod schemas instead of plain interfaces")
    feature_group.add_argument("--zod-dates", action="store_true", help="Use z.date() for date/timestamp types (requires --zod)")
    feature_group.add_argument("-w", "--watch", action="store_true", help="Watch for schema changes and regenerate")
    feature_group.add_argument("--watch-interval", type=int, default=5, help="Watch interval in seconds (default: 5)")
    
    args = parser.parse_args()
    
    # Validate zod-dates requires zod
    if args.zod_dates and not args.zod:
        parser.error("--zod-dates requires --zod")
    
    # Build connection params
    if args.url:
        conn_params = parse_connection_url(args.url)
    else:
        if not args.database:
            parser.error("--database is required when not using --url")
        conn_params = {
            "host": args.host,
            "port": args.port,
            "database": args.database,
            "user": args.user,
            "password": args.password,
        }
    
    # Parse schemas
    schemas = [s.strip() for s in args.schemas.split(",")]
    
    # Watch mode
    if args.watch:
        if not args.output:
            parser.error("--watch requires --output to be specified")
        watch_loop(args, conn_params, schemas, args.watch_interval)
        return
    
    # Single generation
    try:
        output, metadata = run_generation(args, conn_params, schemas)
        write_output(output, args.output, metadata, args.json)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except psycopg2.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
