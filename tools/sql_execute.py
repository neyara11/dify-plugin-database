from collections.abc import Generator
from typing import Any
import math
import re

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


def _normalize_value(value):
    """Replace NaN/Infinity (not valid JSON) with an empty string."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    return value


def _normalize_row(row):
    return tuple(_normalize_value(cell) for cell in row)


class SQLExecuteTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        db_uri = tool_parameters.get("db_uri") or self.runtime.credentials.get("db_uri")
        if not db_uri:
            raise ValueError("Database URI is not provided.")

        query = tool_parameters.get("query").strip()
        format = tool_parameters.get("format", "json")
        config_options = parse_config_options(tool_parameters.get("config_options"))

        # 检查是否为 Vertica 数据库
        if is_vertica_uri(db_uri):
            config = parse_vertica_uri(db_uri)
            config.update(config_options)
            return self._handle_vertica_query(config, query, format)
        # 检查是否为 ClickHouse/MyScale 数据库
        elif is_clickhouse_uri(db_uri):
            config = parse_clickhouse_uri(db_uri)
            config.update(config_options)
            return self._handle_clickhouse_query(config, query, format)
        else:
            db_uri = fix_db_uri_encoding(db_uri)
            engine = get_engine(db_uri, config_options)
            return self._handle_sqlalchemy_query(engine, query, format)

    def _handle_clickhouse_query(self, config: dict, query: str, format: str) -> Generator[ToolInvokeMessage]:
        """处理 ClickHouse/MyScale 查询"""
        try:
            import clickhouse_connect
        except ImportError:
            raise ValueError("ClickHouse driver (clickhouse-connect) is not installed. Please add it to requirements.txt")

        columns = []
        rows = []
        affected_rows = 0
        is_query = False
        error = None
        try:
            client = clickhouse_connect.get_client(**config)
            try:
                if re.match(r'^\s*(SELECT|WITH|SHOW|DESCRIBE|EXISTS)\s+', query, re.IGNORECASE):
                    is_query = True
                    result = client.query(query)
                    columns = list(result.column_names)
                    rows = [_normalize_row(row) for row in result.result_rows]
                else:
                    command_result = client.command(query)
                    affected_rows = command_result if isinstance(command_result, int) else 0
            finally:
                client.close()
        except Exception as e:
            error = str(e)

        if error is not None:
            yield self.create_text_message(f"Error: {error}")
            return

        if not is_query:
            yield self.create_text_message(
                f"Query executed successfully. Affected rows: {affected_rows}"
            )
            return

        if format == "json":
            data = []
            for row in rows:
                row_dict = {}
                for i, column_name in enumerate(columns):
                    value = row[i]
                    if hasattr(value, 'isoformat'):
                        value = value.isoformat()
                    elif hasattr(value, '__str__'):
                        value = str(value)
                    row_dict[column_name] = value
                data.append(row_dict)
            yield self.create_json_message({"result": data})

        elif format == "md":
            if columns and rows:
                header = "| " + " | ".join(columns) + " |"
                separator = "| " + " | ".join(["---"] * len(columns)) + " |"

                table_rows = []
                for row in rows:
                    row_str = "| " + " | ".join(str(cell) if cell is not None else "NULL" for cell in row) + " |"
                    table_rows.append(row_str)

                markdown_table = "\n".join([header, separator] + table_rows)
                yield self.create_text_message(markdown_table)
            else:
                yield self.create_text_message("Query returned no results")

        elif format == "csv":
            import io
            import csv

            output = io.StringIO()
            writer = csv.writer(output)

            if columns:
                writer.writerow(columns)

            for row in rows:
                writer.writerow(row)

            csv_data = output.getvalue()
            yield self.create_blob_message(
                csv_data.encode('utf-8'),
                meta={"mime_type": "text/csv", "filename": "result.csv"}
            )

        elif format == "yaml":
            import yaml

            data = []
            for row in rows:
                row_dict = {}
                for i, column_name in enumerate(columns):
                    row_dict[column_name] = row[i]
                data.append(row_dict)

            yaml_data = yaml.dump({"result": data}, default_flow_style=False, allow_unicode=True)
            yield self.create_blob_message(
                yaml_data.encode('utf-8'),
                meta={"mime_type": "text/yaml", "filename": "result.yaml"}
            )

        elif format == "xlsx":
            import pandas as pd

            df = pd.DataFrame(rows, columns=columns)

            import io
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Results')

            yield self.create_blob_message(
                output.getvalue(),
                meta={
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "filename": "result.xlsx",
                },
            )

        elif format == "html":
            html_data = "<table>\n"

            if columns:
                html_data += "<thead><tr>"
                for col in columns:
                    html_data += f"<th>{col}</th>"
                html_data += "</tr></thead>\n"

            html_data += "<tbody>\n"
            for row in rows:
                html_data += "<tr>"
                for cell in row:
                    html_data += f"<td>{cell if cell is not None else 'NULL'}</td>"
                html_data += "</tr>\n"
            html_data += "</tbody>\n</table>"

            yield self.create_blob_message(
                html_data.encode('utf-8'),
                meta={"mime_type": "text/html", "filename": "result.html"},
            )

        else:
            raise ValueError(f"Unsupported format: {format}")

    def _handle_vertica_query(self, config: dict, query: str, format: str) -> Generator[ToolInvokeMessage]:
        """处理 Vertica 查询"""
        try:
            import vertica_python
        except ImportError:
            raise ValueError("Vertica driver (vertica-python) is not installed. Please add it to requirements.txt")

        columns = []
        rows = []
        is_query = bool(re.match(r'^\s*(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\s+', query, re.IGNORECASE))
        error = None
        try:
            conn = vertica_python.connect(**config)
            try:
                cur = conn.cursor()
                cur.execute(query)
                if is_query:
                    rows = [_normalize_row(row) for row in cur.fetchall()]
                    columns = [desc[0] for desc in cur.description] if cur.description else []
                else:
                    conn.commit()
            finally:
                conn.close()
        except Exception as e:
            error = str(e)

        if error is not None:
            yield self.create_text_message(f"Error: {error}")
            return

        if not is_query:
            yield self.create_text_message(
                "Query executed successfully."
            )
            return

        if format == "json":
            result_data = [dict(zip(columns, row)) for row in rows]
            yield self.create_json_message({"result": result_data})
        elif format == "md":
            if rows:
                from tabulate import tabulate
                table = tabulate(rows, headers=columns, tablefmt="pipe")
                yield self.create_text_message(table)
            else:
                yield self.create_text_message("Query returned no results")
        elif format == "csv":
            import io
            import csv
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(columns)
            writer.writerows(rows)
            csv_data = output.getvalue()
            yield self.create_blob_message(
                csv_data.encode('utf-8'),
                meta={"mime_type": "text/csv", "filename": "result.csv"}
            )
        elif format == "yaml":
            import yaml
            result_data = [dict(zip(columns, row)) for row in rows]
            yaml_data = yaml.dump({"result": result_data}, default_flow_style=False, allow_unicode=True)
            yield self.create_blob_message(
                yaml_data.encode('utf-8'),
                meta={"mime_type": "text/yaml", "filename": "result.yaml"},
            )
        elif format == "xlsx":
            import pandas as pd
            df = pd.DataFrame(rows, columns=columns)
            import io
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Results')
            yield self.create_blob_message(
                output.getvalue(),
                meta={
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "filename": "result.xlsx",
                },
            )
        elif format == "html":
            html_data = "<table>\n"
            if columns:
                html_data += "<thead><tr>"
                for col in columns:
                    html_data += f"<th>{col}</th>"
                html_data += "</tr></thead>\n"
            html_data += "<tbody>\n"
            for row in rows:
                html_data += "<tr>"
                for cell in row:
                    html_data += f"<td>{cell if cell is not None else 'NULL'}</td>"
                html_data += "</tr>\n"
            html_data += "</tbody>\n</table>"
            yield self.create_blob_message(
                html_data.encode('utf-8'),
                meta={"mime_type": "text/html", "filename": "result.html"},
            )
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _handle_sqlalchemy_query(self, engine, query: str, format: str) -> Generator[ToolInvokeMessage]:
        """处理 SQLAlchemy 支持的数据库查询"""
        if re.match(r'^\s*(SELECT|WITH)\s+', query, re.IGNORECASE):
            with engine.connect() as conn:
                result = conn.exec_driver_sql(query)
                rows = [_normalize_row(row) for row in result.fetchall()]
                columns = list(result.keys())

            if format == "json":
                result_data = [dict(zip(columns, row)) for row in rows]
                yield self.create_json_message({"result": result_data})
            elif format == "md":
                from tabulate import tabulate
                if rows:
                    table = tabulate(rows, headers=columns, tablefmt="pipe")
                    yield self.create_text_message(table)
                else:
                    yield self.create_text_message("Query returned no results")
            elif format == "csv":
                import io
                import csv
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(columns)
                writer.writerows(rows)
                csv_data = output.getvalue()
                yield self.create_blob_message(
                    csv_data.encode('utf-8'),
                    meta={"mime_type": "text/csv", "filename": "result.csv"}
                )
            elif format == "yaml":
                import yaml
                result_data = [dict(zip(columns, row)) for row in rows]
                yaml_data = yaml.dump({"result": result_data}, default_flow_style=False, allow_unicode=True)
                yield self.create_blob_message(
                    yaml_data.encode('utf-8'),
                    meta={"mime_type": "text/yaml", "filename": "result.yaml"},
                )
            elif format == "xlsx":
                import pandas as pd
                df = pd.DataFrame(rows, columns=columns)
                import io
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Results')
                yield self.create_blob_message(
                    output.getvalue(),
                    meta={
                        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "filename": "result.xlsx",
                    },
                )
            elif format == "html":
                html_data = "<table>\n"
                if columns:
                    html_data += "<thead><tr>"
                    for col in columns:
                        html_data += f"<th>{col}</th>"
                    html_data += "</tr></thead>\n"
                html_data += "<tbody>\n"
                for row in rows:
                    html_data += "<tr>"
                    for cell in row:
                        html_data += f"<td>{cell if cell is not None else 'NULL'}</td>"
                    html_data += "</tr>\n"
                html_data += "</tbody>\n</table>"
                yield self.create_blob_message(
                    html_data.encode('utf-8'),
                    meta={"mime_type": "text/html", "filename": "result.html"},
                )
            else:
                raise ValueError(f"Unsupported format: {format}")
        else:
            try:
                with engine.begin() as conn:
                    result = conn.exec_driver_sql(query)
                    affected_rows = result.rowcount
            except Exception as e:
                yield self.create_text_message(f"Error: {str(e)}")
                return
            yield self.create_text_message(
                f"Query executed successfully. Affected rows: {affected_rows}"
            )
