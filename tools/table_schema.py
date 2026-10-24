from collections.abc import Generator
from typing import Any
import json

from sqlalchemy import inspect
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.db_utils import (
    fix_db_uri_encoding,
    get_engine,
    is_clickhouse_uri,
    parse_clickhouse_uri,
    is_vertica_uri,
    parse_vertica_uri,
    parse_config_options,
)


class QueryTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        db_uri = tool_parameters.get("db_uri") or self.runtime.credentials.get("db_uri")
        if not db_uri:
            raise ValueError("Database URI is not provided.")

        tables = tool_parameters.get("tables")
        schema = tool_parameters.get("schema")
        if not schema:
            # sometimes the schema is empty string, it must be None
            schema = None

        config_options = parse_config_options(tool_parameters.get("config_options"))

        # 检查是否为 Vertica 数据库
        if is_vertica_uri(db_uri):
            config = parse_vertica_uri(db_uri)
            config.update(config_options)
            return self._get_vertica_schema(config, tables, schema)
        # 检查是否为 ClickHouse/MyScale 数据库
        elif is_clickhouse_uri(db_uri):
            config = parse_clickhouse_uri(db_uri)
            config.update(config_options)
            return self._get_clickhouse_schema(config, tables, schema)
        else:
            db_uri = fix_db_uri_encoding(db_uri)
            engine = get_engine(db_uri, config_options)
            return self._get_sqlalchemy_schema(engine, tables, schema)

    def _get_clickhouse_schema(self, config: dict, tables: str, schema: str) -> Generator[ToolInvokeMessage]:
        """获取 ClickHouse/MyScale 表结构"""
        try:
            import clickhouse_connect
        except ImportError:
            raise ValueError("ClickHouse driver (clickhouse-connect) is not installed. Please add it to requirements.txt")

        schema_info = {}
        error = None
        try:
            client = clickhouse_connect.get_client(**config)
            try:
                # 获取所有表名或使用指定的表名
                if not tables:
                    tables_query = "SELECT name FROM system.tables WHERE database = currentDatabase()"
                    result = client.query(tables_query)
                    tables_list = [row[0] for row in result.result_rows]
                else:
                    tables_list = [t.strip() for t in tables.split(",")]

                for table_name in tables_list:
                    try:
                        columns_query = f"""
                        SELECT
                            name,
                            type,
                            is_in_primary_key,
                            is_in_sorting_key,
                            is_in_partition_key,
                            comment
                        FROM system.columns
                        WHERE database = currentDatabase() AND table = '{table_name}'
                        ORDER BY position
                        """

                        columns_result = client.query(columns_query)

                        table_info = {
                            "table_name": table_name,
                            "columns": [],
                            "primary_keys": [],
                            "sorting_keys": [],
                            "partition_keys": [],
                            "engine": "",
                            "comment": ""
                        }

                        try:
                            table_query = f"""
                            SELECT engine, comment
                            FROM system.tables
                            WHERE database = currentDatabase() AND name = '{table_name}'
                            """
                            table_result = client.query(table_query)
                            if table_result.result_rows:
                                row = table_result.result_rows[0]
                                table_info["engine"] = row[0]
                                table_info["comment"] = row[1] or ""
                        except Exception:
                            pass

                        for row in columns_result.result_rows:
                            column_info = {
                                "name": row[0],
                                "type": row[1],
                                "nullable": "Nullable" in str(row[1]),
                                "default": None,
                                "comment": row[5] or ""
                            }
                            table_info["columns"].append(column_info)

                            if row[2]:
                                table_info["primary_keys"].append(row[0])
                            if row[3]:
                                table_info["sorting_keys"].append(row[0])
                            if row[4]:
                                table_info["partition_keys"].append(row[0])

                        schema_info[table_name] = table_info

                    except Exception as e:
                        schema_info[table_name] = f"Error getting table schema: {str(e)}"
            finally:
                client.close()
        except Exception as e:
            error = str(e)

        if error is not None:
            yield self.create_text_message(f"Error: {error}")
            return

        yield self.create_text_message(json.dumps(schema_info, ensure_ascii=False))

    def _get_vertica_schema(self, config: dict, tables: str, schema: str) -> Generator[ToolInvokeMessage]:
        """获取 Vertica 表结构"""
        try:
            import vertica_python
        except ImportError:
            raise ValueError("Vertica driver (vertica-python) is not installed. Please add it to requirements.txt")

        schema_info = {}
        error = None
        try:
            conn = vertica_python.connect(**config)
            try:
                if schema:
                    schema_filter = f"'{schema}'"
                else:
                    schema_filter = "CURRENT_SCHEMA()"

                if not tables:
                    tables_query = f"""
                    SELECT TABLE_NAME FROM v_catalog.tables
                    WHERE TABLE_SCHEMA = {schema_filter} AND IS_SYSTEM_TABLE = false
                    ORDER BY TABLE_NAME
                    """
                    cur = conn.cursor()
                    cur.execute(tables_query)
                    tables_list = [row[0] for row in cur.fetchall()]
                else:
                    tables_list = [t.strip() for t in tables.split(",")]

                for table_name in tables_list:
                    try:
                        columns_query = f"""
                        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                        FROM v_catalog.columns
                        WHERE TABLE_SCHEMA = {schema_filter} AND TABLE_NAME = '{table_name}'
                        ORDER BY ORDINAL_POSITION
                        """
                        cur = conn.cursor()
                        cur.execute(columns_query)
                        columns_result = cur.fetchall()

                        pk_query = f"""
                        SELECT COLUMN_NAME FROM v_catalog.primary_keys
                        WHERE TABLE_SCHEMA = {schema_filter} AND TABLE_NAME = '{table_name}'
                        ORDER BY ORDINAL_POSITION
                        """
                        cur.execute(pk_query)
                        pk_result = cur.fetchall()
                        pk_columns = [row[0] for row in pk_result]

                        table_info = {
                            "table_name": table_name,
                            "columns": [],
                            "primary_keys": pk_columns,
                            "foreign_keys": [],
                            "indexes": [],
                            "comment": "",
                        }

                        for row in columns_result:
                            column_info = {
                                "name": row[0],
                                "type": row[1],
                                "nullable": row[2],
                                "default": row[3],
                                "comment": "",
                            }
                            table_info["columns"].append(column_info)

                        schema_info[table_name] = table_info

                    except Exception as e:
                        schema_info[table_name] = f"Error getting table schema: {str(e)}"
            finally:
                conn.close()
        except Exception as e:
            error = str(e)

        if error is not None:
            yield self.create_text_message(f"Error: {error}")
            return

        yield self.create_text_message(json.dumps(schema_info, ensure_ascii=False))

    def _get_sqlalchemy_schema(self, engine, tables: str, schema: str) -> Generator[ToolInvokeMessage]:
        """获取 SQLAlchemy 支持的数据库表结构"""
        with engine.connect() as conn:
            inspector = inspect(conn)
            tables = tables.split(",") if tables else inspector.get_table_names(schema=schema)

            schema_info = {}
            for table_name in tables:
                # Basic table info
                table_info = {
                    "table_name": table_name,
                    "columns": [],
                    "primary_keys": inspector.get_pk_constraint(table_name, schema=schema).get('constrained_columns', []),
                    "foreign_keys": [],
                    "indexes": []
                }

                # Get table comment
                try:
                    table_info["comment"] = inspector.get_table_comment(table_name, schema=schema).get('text', '')
                except NotImplementedError:
                    table_info["comment"] = ""

                # Get foreign keys
                try:
                    for fk in inspector.get_foreign_keys(table_name, schema=schema):
                        table_info["foreign_keys"].append({
                            "referred_table": fk['referred_table'],
                            "referred_columns": fk['referred_columns'],
                            "constrained_columns": fk['constrained_columns']
                        })
                except NotImplementedError:
                    pass

                # Get indexes
                try:
                    for idx in inspector.get_indexes(table_name, schema=schema):
                        table_info["indexes"].append({
                            "name": idx['name'],
                            "columns": idx['column_names'],
                            "unique": idx['unique']
                        })
                except NotImplementedError:
                    pass

                # Get columns
                try:
                    columns = inspector.get_columns(table_name, schema=schema)
                    table_info["columns"] = [
                        {
                            "name": col["name"],
                            "type": str(col["type"]),
                            "nullable": col.get("nullable", True),
                            "default": col.get("default"),
                            "comment": col.get("comment", ""),
                        }
                        for col in columns
                    ]

                    schema_info[table_name] = table_info
                except Exception as e:
                    schema_info[table_name] = f"Error getting schema: {str(e)}"
        yield self.create_text_message(json.dumps(schema_info, ensure_ascii=False))
