#!/usr/bin/env python3
"""
pg2ts MCP Server

Provides PostgreSQL schema tools for AI agents:
- pg2ts_generate: Generate TypeScript types from database schema
- pg2ts_schema: Get database schema as JSON (tables, columns, types)
"""

import json
import sys
from typing import Optional
from dataclasses import dataclass

try:
    import psycopg2
except ImportError:
    print("Error: psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

# Import from main module
from pg2ts import (
    fetch_tables,
    fetch_enums,
    generate_typescript,
    generate_drizzle_schema,
    generate_json_metadata,
    parse_connection_url,
    Table,
    Column,
    PgEnum,
)

# FastMCP is optional
try:
    from fastmcp import FastMCP
    mcp = FastMCP("pg2ts")
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    
    class DummyMCP:
        def tool(self):
            def decorator(f):
                return f
            return decorator
    mcp = DummyMCP()


@mcp.tool()
def pg2ts_generate(
    connection_string: str,
    format: str = "typescript",
    schemas: str = "public",
    with_zod: bool = False,
) -> str:
    """
    Generate TypeScript types from PostgreSQL database schema.
    
    Returns generated TypeScript code that can be written to a .ts file.
    Supports multiple output formats:
    - typescript: Standard interfaces with Row and Insert types
    - zod: Zod schemas with runtime validation
    - drizzle: Complete Drizzle ORM schema
    
    Args:
        connection_string: PostgreSQL connection URL 
                          (e.g., postgresql://user:pass@host:5432/dbname)
        format: Output format - "typescript", "zod", or "drizzle"
        schemas: Comma-separated schema names (default: "public")
        with_zod: Include Zod schemas in typescript output
    """
    try:
        conn_params = parse_connection_url(connection_string)
        schema_list = [s.strip() for s in schemas.split(",")]
        
        conn = psycopg2.connect(**conn_params)
        enums = fetch_enums(conn, schema_list)
        
        fetch_metadata = format == "drizzle"
        tables = fetch_tables(conn, schema_list, True, fetch_metadata, enums)
        conn.close()
        
        if not tables:
            return json.dumps({"error": "No tables found in specified schemas"})
        
        # Generate based on format
        if format == "drizzle":
            output = generate_drizzle_schema(tables, enums)
        else:
            output = generate_typescript(
                tables,
                include_schema=False,
                with_metadata=False,
                zod=with_zod or format == "zod",
                zod_dates=False,
                enums=enums
            )
        
        return output
        
    except Exception as e:
        return json.dumps({
            "error": str(e),
            "hint": "Check connection string format: postgresql://user:pass@host:5432/dbname"
        })


@mcp.tool()
def pg2ts_schema(
    connection_string: str,
    schemas: str = "public",
) -> str:
    """
    Get database schema information as JSON.
    
    Returns detailed schema information including:
    - tables: All tables with columns, types, constraints
    - enums: PostgreSQL enum types and their values
    - columns: Column details (name, type, nullable, default, etc.)
    
    Useful for understanding database structure before generating code
    or for schema documentation.
    
    Args:
        connection_string: PostgreSQL connection URL
        schemas: Comma-separated schema names (default: "public")
    """
    try:
        conn_params = parse_connection_url(connection_string)
        schema_list = [s.strip() for s in schemas.split(",")]
        
        conn = psycopg2.connect(**conn_params)
        enums = fetch_enums(conn, schema_list)
        tables = fetch_tables(conn, schema_list, True, True, enums)
        conn.close()
        
        if not tables:
            return json.dumps({"error": "No tables found in specified schemas"})
        
        # Build schema info
        result = {
            "schemas": schema_list,
            "table_count": len(tables),
            "enum_count": len(enums),
            "tables": [],
            "enums": []
        }
        
        for table in tables:
            table_info = {
                "schema": table.schema,
                "name": table.name,
                "comment": table.comment,
                "column_count": len(table.columns),
                "columns": []
            }
            
            for col in table.columns:
                col_info = {
                    "name": col.name,
                    "type": col.data_type,
                    "nullable": col.is_nullable,
                    "is_array": col.is_array,
                    "is_primary_key": col.is_primary_key,
                }
                if col.comment:
                    col_info["comment"] = col.comment
                if col.column_default:
                    col_info["default"] = col.column_default
                if col.fk_table:
                    col_info["foreign_key"] = {
                        "table": col.fk_table,
                        "column": col.fk_column
                    }
                table_info["columns"].append(col_info)
            
            result["tables"].append(table_info)
        
        for enum_name, enum_obj in enums.items():
            result["enums"].append({
                "name": enum_obj.name,
                "schema": enum_obj.schema,
                "values": enum_obj.values
            })
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def pg2ts_table(
    connection_string: str,
    table: str,
    schema: str = "public",
) -> str:
    """
    Get detailed information about a specific table.
    
    Returns columns, types, constraints, and relationships for one table.
    More focused than pg2ts_schema when you only need one table.
    
    Args:
        connection_string: PostgreSQL connection URL
        table: Table name
        schema: Schema name (default: "public")
    """
    try:
        conn_params = parse_connection_url(connection_string)
        
        conn = psycopg2.connect(**conn_params)
        enums = fetch_enums(conn, [schema])
        tables = fetch_tables(conn, [schema], True, True, enums)
        conn.close()
        
        # Find the requested table
        target = None
        for t in tables:
            if t.name == table and t.schema == schema:
                target = t
                break
        
        if not target:
            return json.dumps({
                "error": f"Table '{schema}.{table}' not found",
                "available_tables": [f"{t.schema}.{t.name}" for t in tables]
            })
        
        # Build detailed info
        result = {
            "schema": target.schema,
            "name": target.name,
            "full_name": f"{target.schema}.{target.name}",
            "comment": target.comment,
            "columns": []
        }
        
        primary_keys = []
        foreign_keys = []
        
        for col in target.columns:
            col_info = {
                "name": col.name,
                "type": col.data_type,
                "nullable": col.is_nullable,
                "is_array": col.is_array,
            }
            if col.comment:
                col_info["comment"] = col.comment
            if col.column_default:
                col_info["default"] = col.column_default
            if col.is_primary_key:
                col_info["is_primary_key"] = True
                primary_keys.append(col.name)
            if col.fk_table:
                fk = {
                    "column": col.name,
                    "references_table": col.fk_table,
                    "references_column": col.fk_column
                }
                col_info["foreign_key"] = fk
                foreign_keys.append(fk)
            
            result["columns"].append(col_info)
        
        result["primary_keys"] = primary_keys
        result["foreign_keys"] = foreign_keys
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)})


def main():
    """Run the MCP server."""
    if not HAS_MCP:
        print("Error: fastmcp not installed.", file=sys.stderr)
        print("Install with: pip install fastmcp", file=sys.stderr)
        print("\nYou can still use the tool functions directly:", file=sys.stderr)
        print("  from mcp_server import pg2ts_generate, pg2ts_schema, pg2ts_table", file=sys.stderr)
        sys.exit(1)
    mcp.run()


if __name__ == "__main__":
    main()
