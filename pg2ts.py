#!/usr/bin/env python3
"""
pg2ts - Generate TypeScript types from PostgreSQL schemas

A lightweight CLI tool to sync your database schema with TypeScript interfaces.
No runtime dependencies, just pure type generation.

Usage:
    pg2ts --host localhost --db mydb --user postgres --output types.ts
    pg2ts --url "postgresql://user:pass@host:5432/db" --output types.ts
    pg2ts --url "..." --drizzle -o schema.ts  # Generate Drizzle ORM schema
"""

import argparse
import json
import re
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


@dataclass
class PgEnum:
    """PostgreSQL enum type."""
    name: str
    schema: str
    values: list[str]


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

# PostgreSQL to Drizzle type mapping
PG_TO_DRIZZLE = {
    # Serial types
    "serial": "serial",
    "bigserial": "bigserial",
    "smallserial": "smallserial",
    
    # Numeric types
    "smallint": "smallint",
    "integer": "integer",
    "bigint": "bigint",
    "int2": "smallint",
    "int4": "integer",
    "int8": "bigint",
    "decimal": "decimal",
    "numeric": "numeric",
    "real": "real",
    "double precision": "doublePrecision",
    "float4": "real",
    "float8": "doublePrecision",
    
    # Boolean
    "boolean": "boolean",
    "bool": "boolean",
    
    # String types
    "character varying": "varchar",
    "varchar": "varchar",
    "character": "char",
    "char": "char",
    "text": "text",
    "citext": "text",
    "uuid": "uuid",
    "name": "text",
    
    # Date/Time
    "timestamp": "timestamp",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamp",
    "timestamptz": "timestamp",
    "date": "date",
    "time": "time",
    "time without time zone": "time",
    "time with time zone": "time",
    "timetz": "time",
    "interval": "interval",
    
    # JSON
    "json": "json",
    "jsonb": "jsonb",
    
    # Binary
    "bytea": "text",  # Drizzle doesn't have bytea, use text as fallback
    
    # Network
    "inet": "inet",
    "cidr": "cidr",
    "macaddr": "macaddr",
}


@dataclass
class Column:
    name: str
    data_type: str
    is_nullable: bool
    column_default: Optional[str]
    is_array: bool = False
    comment: Optional[str] = None
    # Additional metadata for Drizzle
    char_max_length: Optional[int] = None
    numeric_precision: Optional[int] = None
    numeric_scale: Optional[int] = None
    is_primary_key: bool = False
    is_serial: bool = False  # Track if this is a serial/identity column
    enum_type: Optional[str] = None  # Name of the enum type if this column uses one
    fk_table: Optional[str] = None  # Foreign key target table
    fk_column: Optional[str] = None  # Foreign key target column


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


def get_ts_type_with_enums(pg_type: str, is_array: bool = False, enum_map: dict[str, PgEnum] = None) -> str:
    """Convert PostgreSQL type to TypeScript type, with enum support."""
    # Handle array types
    if pg_type.startswith("_"):
        pg_type = pg_type[1:]
        is_array = True
    
    if pg_type.endswith("[]"):
        pg_type = pg_type[:-2]
        is_array = True
    
    # Check if this is an enum type
    if enum_map and pg_type in enum_map:
        ts_type = snake_to_pascal(pg_type)
    else:
        ts_type = PG_TO_TS.get(pg_type.lower(), "unknown")
    
    if is_array:
        return f"{ts_type}[]"
    return ts_type


def get_zod_type_with_enums(pg_type: str, is_array: bool = False, use_dates: bool = False, enum_map: dict[str, PgEnum] = None) -> str:
    """Convert PostgreSQL type to Zod type, with enum support."""
    # Handle array types
    if pg_type.startswith("_"):
        pg_type = pg_type[1:]
        is_array = True
    
    if pg_type.endswith("[]"):
        pg_type = pg_type[:-2]
        is_array = True
    
    # Check if this is an enum type
    if enum_map and pg_type in enum_map:
        zod_type = f"{snake_to_pascal(pg_type)}Schema"
    elif use_dates and pg_type.lower() in DATE_TYPES:
        zod_type = "z.coerce.date()"
    else:
        zod_type = PG_TO_ZOD.get(pg_type.lower(), "z.unknown()")
    
    if is_array:
        return f"z.array({zod_type})"
    return zod_type


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


def fetch_enums(conn, schemas: list[str]) -> dict[str, PgEnum]:
    """Fetch all enum types from PostgreSQL."""
    enums = {}
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                n.nspname as schema,
                t.typname as name,
                e.enumlabel as value
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            JOIN pg_namespace n ON t.typnamespace = n.oid
            WHERE n.nspname = ANY(%s)
            ORDER BY t.typname, e.enumsortorder
        """, (schemas,))
        
        for row in cur.fetchall():
            enum_name = row["name"]
            if enum_name not in enums:
                enums[enum_name] = PgEnum(
                    name=enum_name,
                    schema=row["schema"],
                    values=[]
                )
            enums[enum_name].values.append(row["value"])
    
    return enums


def fetch_primary_keys(conn, schema: str, table_name: str) -> set[str]:
    """Fetch primary key columns for a table."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT a.attname as column_name
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE i.indisprimary
              AND c.relname = %s
              AND n.nspname = %s
        """, (table_name, schema))
        return {row["column_name"] for row in cur.fetchall()}


def fetch_foreign_keys(conn, schema: str, table_name: str) -> dict[str, tuple[str, str]]:
    """Fetch foreign key information for a table. Returns {column_name: (referenced_table, referenced_column)}."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT
                kcu.column_name,
                ccu.table_name AS referenced_table,
                ccu.column_name AS referenced_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = %s
              AND tc.table_schema = %s
        """, (table_name, schema))
        return {row["column_name"]: (row["referenced_table"], row["referenced_column"]) for row in cur.fetchall()}


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


def fetch_tables(conn, schemas: list[str], fetch_comments_flag: bool = False, fetch_metadata: bool = False, enum_map: dict[str, PgEnum] = None) -> list[Table]:
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
            
            # Fetch primary keys and foreign keys if metadata is needed
            primary_keys = set()
            foreign_keys = {}
            if fetch_metadata:
                primary_keys = fetch_primary_keys(conn, schema, table_name)
                foreign_keys = fetch_foreign_keys(conn, schema, table_name)
            
            # Get columns for this table with extended metadata
            cur.execute("""
                SELECT 
                    column_name,
                    data_type,
                    udt_name,
                    is_nullable,
                    column_default,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema, table_name))
            
            columns = []
            for col in cur.fetchall():
                # Use udt_name for better type detection (handles arrays)
                data_type = col["udt_name"]
                is_array = data_type.startswith("_")
                
                # Detect serial columns (have nextval() default)
                column_default = col["column_default"]
                is_serial = column_default and "nextval(" in str(column_default)
                
                # Check if this column uses an enum type
                base_type = data_type[1:] if data_type.startswith("_") else data_type
                enum_type = base_type if enum_map and base_type in enum_map else None
                
                # Get foreign key info
                fk_table = None
                fk_column = None
                if col["column_name"] in foreign_keys:
                    fk_table, fk_column = foreign_keys[col["column_name"]]
                
                columns.append(Column(
                    name=col["column_name"],
                    data_type=data_type,
                    is_nullable=col["is_nullable"] == "YES",
                    column_default=column_default,
                    is_array=is_array,
                    comment=column_comments.get(col["column_name"]),
                    char_max_length=col["character_maximum_length"],
                    numeric_precision=col["numeric_precision"],
                    numeric_scale=col["numeric_scale"],
                    is_primary_key=col["column_name"] in primary_keys,
                    is_serial=is_serial,
                    enum_type=enum_type,
                    fk_table=fk_table,
                    fk_column=fk_column
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


def generate_enum_types(enums: dict[str, PgEnum], zod: bool = False) -> list[str]:
    """Generate TypeScript enum types."""
    lines = []
    
    for enum_name, enum in sorted(enums.items()):
        pascal_name = snake_to_pascal(enum_name)
        values_str = ", ".join(f"'{v}'" for v in enum.values)
        
        # Generate TypeScript union type
        lines.append(f"export type {pascal_name} = {' | '.join(repr(v) for v in enum.values)};")
        lines.append(f"export const {pascal_name}Values = [{values_str}] as const;")
        
        # Generate Zod schema if requested
        if zod:
            lines.append(f"export const {pascal_name}Schema = z.enum([{values_str}]);")
        
        lines.append("")
    
    return lines


def generate_drizzle_schema(tables: list[Table], enums: dict[str, PgEnum]) -> str:
    """Generate Drizzle ORM schema from tables and enums."""
    lines = [
        "// Auto-generated by pg2ts",
        "// https://github.com/indiekitai/pg2ts",
        "// Do not edit manually!",
        "",
    ]
    
    # Collect all drizzle types needed
    drizzle_types = set()
    has_enums = len(enums) > 0
    has_relations = any(col.fk_table for table in tables for col in table.columns)
    
    for table in tables:
        for col in table.columns:
            if col.enum_type:
                continue  # Enums are handled separately
            base_type = col.data_type[1:] if col.data_type.startswith("_") else col.data_type
            drizzle_type = PG_TO_DRIZZLE.get(base_type.lower())
            if drizzle_type:
                drizzle_types.add(drizzle_type)
    
    # Always add pgTable
    imports = ["pgTable"]
    if has_enums:
        imports.append("pgEnum")
    imports.extend(sorted(drizzle_types))
    
    lines.append(f"import {{ {', '.join(imports)} }} from 'drizzle-orm/pg-core';")
    if has_relations:
        lines.append("// Note: Add relations import if needed: import { relations } from 'drizzle-orm';")
    lines.append("")
    
    # Generate enums
    if enums:
        lines.append("// Enums")
        for enum_name, enum in sorted(enums.items()):
            camel_name = snake_to_camel(enum_name) + "Enum"
            values_str = ", ".join(f"'{v}'" for v in enum.values)
            lines.append(f"export const {camel_name} = pgEnum('{enum_name}', [{values_str}]);")
        lines.append("")
    
    # Generate tables
    lines.append("// Tables")
    for table in tables:
        table_var_name = snake_to_camel(table.name)
        
        # Table JSDoc comment
        if table.comment:
            lines.append(f"/** {table.comment} */")
        
        lines.append(f"export const {table_var_name} = pgTable('{table.name}', {{")
        
        for col in table.columns:
            col_def = _generate_drizzle_column(col, enums, tables)
            # Column JSDoc comment
            if col.comment:
                lines.append(f"  /** {col.comment} */")
            lines.append(f"  {col.name}: {col_def},")
        
        lines.append("});")
        lines.append("")
    
    # Generate TypeScript types from Drizzle schema
    lines.append("// Inferred types")
    for table in tables:
        table_var_name = snake_to_camel(table.name)
        pascal_name = snake_to_pascal(table.name)
        lines.append(f"export type {pascal_name} = typeof {table_var_name}.$inferSelect;")
        lines.append(f"export type {pascal_name}Insert = typeof {table_var_name}.$inferInsert;")
    lines.append("")
    
    return "\n".join(lines)


def _generate_drizzle_column(col: Column, enums: dict[str, PgEnum], tables: list[Table]) -> str:
    """Generate a single Drizzle column definition."""
    parts = []
    
    # Base type
    base_type = col.data_type[1:] if col.data_type.startswith("_") else col.data_type
    
    if col.enum_type:
        # Enum column
        enum_var_name = snake_to_camel(col.enum_type) + "Enum"
        parts.append(f"{enum_var_name}('{col.name}')")
    elif col.is_serial and base_type.lower() in ("int4", "integer", "serial"):
        # Serial column
        parts.append(f"serial('{col.name}')")
    elif col.is_serial and base_type.lower() in ("int8", "bigint", "bigserial"):
        # Bigserial column
        parts.append(f"bigserial('{col.name}', {{ mode: 'number' }})")
    elif base_type.lower() in ("varchar", "character varying") and col.char_max_length:
        # VARCHAR with length
        parts.append(f"varchar('{col.name}', {{ length: {col.char_max_length} }})")
    elif base_type.lower() in ("char", "character") and col.char_max_length:
        # CHAR with length
        parts.append(f"char('{col.name}', {{ length: {col.char_max_length} }})")
    elif base_type.lower() in ("numeric", "decimal") and col.numeric_precision:
        # NUMERIC with precision/scale
        if col.numeric_scale:
            parts.append(f"numeric('{col.name}', {{ precision: {col.numeric_precision}, scale: {col.numeric_scale} }})")
        else:
            parts.append(f"numeric('{col.name}', {{ precision: {col.numeric_precision} }})")
    elif base_type.lower() in ("timestamp", "timestamptz", "timestamp with time zone", "timestamp without time zone"):
        # Timestamp - check if it has time zone
        if base_type.lower() in ("timestamptz", "timestamp with time zone"):
            parts.append(f"timestamp('{col.name}', {{ withTimezone: true }})")
        else:
            parts.append(f"timestamp('{col.name}')")
    elif base_type.lower() == "bigint" or base_type.lower() == "int8":
        # Bigint needs mode specification
        parts.append(f"bigint('{col.name}', {{ mode: 'number' }})")
    else:
        # Standard type mapping
        drizzle_type = PG_TO_DRIZZLE.get(base_type.lower(), "text")
        parts.append(f"{drizzle_type}('{col.name}')")
    
    col_str = parts[0]
    
    # Add modifiers
    if col.is_primary_key:
        col_str += ".primaryKey()"
    
    if not col.is_nullable and not col.is_primary_key:
        col_str += ".notNull()"
    
    # Handle default values
    if col.column_default and not col.is_serial:
        default_val = _parse_default_value(col.column_default, base_type)
        if default_val:
            col_str += default_val
    
    # Handle foreign keys
    if col.fk_table:
        fk_table_var = snake_to_camel(col.fk_table)
        # Check if referenced table exists in our tables list
        if any(t.name == col.fk_table for t in tables):
            col_str += f".references(() => {fk_table_var}.{col.fk_column})"
    
    return col_str


def _parse_default_value(default_str: str, pg_type: str) -> Optional[str]:
    """Parse PostgreSQL default value into Drizzle default."""
    if not default_str:
        return None
    
    default_lower = default_str.lower()
    
    # Skip nextval (serial columns)
    if "nextval(" in default_lower:
        return None
    
    # NOW() / CURRENT_TIMESTAMP
    if "now()" in default_lower or "current_timestamp" in default_lower:
        return ".defaultNow()"
    
    # Boolean defaults
    if default_lower in ("true", "false"):
        return f".default({default_lower})"
    
    # Numeric defaults (including negative numbers and type casts like '123'::integer)
    # Handle: -1, 0, 123, 1.5, '-1'::integer, etc.
    numeric_match = re.match(r"^'?(-?\d+(?:\.\d+)?)'?(?:::[\w\s]+)?$", default_str)
    if numeric_match:
        return f".default({numeric_match.group(1)})"
    
    # String defaults (with type casting like 'value'::text)
    string_match = re.match(r"^'([^']*)'(?:::[\w\s]+)?$", default_str)
    if string_match:
        value = string_match.group(1)
        # Check if it's actually a number that was quoted
        if re.match(r"^-?\d+(\.\d+)?$", value):
            return f".default({value})"
        # Escape single quotes in the value
        value = value.replace("'", "\\'")
        return f".default('{value}')"
    
    # UUID generation
    if "gen_random_uuid()" in default_lower or "uuid_generate" in default_lower:
        return ".defaultRandom()"
    
    # For other complex defaults, skip them (user can add manually)
    return None


def generate_typescript(
    tables: list[Table], 
    include_schema: bool = False,
    with_metadata: bool = False,
    zod: bool = False,
    zod_dates: bool = False,
    enums: dict[str, PgEnum] = None
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
    
    # Generate enum types first
    if enums:
        lines.append("// Enum types")
        lines.extend(generate_enum_types(enums, zod))
    
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
                zod_type = get_zod_type_with_enums(col.data_type, col.is_array, zod_dates, enums)
                
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
                zod_type = get_zod_type_with_enums(col.data_type, col.is_array, zod_dates, enums)
                if col.comment:
                    lines.append(f"  /** {col.comment} */")
                lines.append(f"  {col.name}: {zod_type},")
            for col in optional_cols:
                zod_type = get_zod_type_with_enums(col.data_type, col.is_array, zod_dates, enums)
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
                ts_type = get_ts_type_with_enums(col.data_type, col.is_array, enums)
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
                    ts_type = get_ts_type_with_enums(col.data_type, col.is_array, enums)
                    if col.comment:
                        lines.append(f"  /** {col.comment} */")
                    lines.append(f"  {col.name}: {ts_type};")
                for col in optional_cols:
                    ts_type = get_ts_type_with_enums(col.data_type, col.is_array, enums)
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


def generate_json_metadata(tables: list[Table], output_file: Optional[str], zod: bool = False, enums: dict[str, PgEnum] = None) -> dict:
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
    
    # Add enum count
    enum_count = len(enums) if enums else 0
    
    result = {
        "tables": table_data,
        "types_generated": types_count,
        "output_file": output_file or "stdout"
    }
    
    if enums:
        result["enums"] = [
            {"name": e.name, "values": e.values}
            for e in enums.values()
        ]
        result["enums_count"] = enum_count
    
    return result


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
    
    # Fetch enums first
    enums = fetch_enums(conn, schemas)
    
    # Fetch tables with extended metadata if drizzle mode is enabled
    fetch_metadata = getattr(args, 'drizzle', False)
    tables = fetch_tables(conn, schemas, fetch_comments_flag, fetch_metadata, enums)
    conn.close()
    
    if not tables:
        raise ValueError("No tables found in specified schemas.")
    
    # Generate output based on mode
    if getattr(args, 'drizzle', False):
        output = generate_drizzle_schema(tables, enums)
    else:
        output = generate_typescript(
            tables, 
            args.include_schema,
            args.with_metadata,
            args.zod,
            args.zod_dates,
            enums
        )
    
    # Generate JSON metadata
    metadata = generate_json_metadata(tables, args.output, args.zod, enums)
    
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
  pg2ts --url "..." --drizzle -o schema.ts         # Generate Drizzle ORM schema
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
    feature_group.add_argument("--drizzle", action="store_true", help="Generate Drizzle ORM schema instead of plain interfaces")
    feature_group.add_argument("-w", "--watch", action="store_true", help="Watch for schema changes and regenerate")
    feature_group.add_argument("--watch-interval", type=int, default=5, help="Watch interval in seconds (default: 5)")
    
    args = parser.parse_args()
    
    # Validate zod-dates requires zod
    if args.zod_dates and not args.zod:
        parser.error("--zod-dates requires --zod")
    
    # Validate drizzle is mutually exclusive with zod
    if args.drizzle and args.zod:
        parser.error("--drizzle and --zod are mutually exclusive")
    
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
