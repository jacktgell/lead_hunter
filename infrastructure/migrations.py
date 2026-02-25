from typing import Dict, Any, Type

from sqlalchemy import Engine, inspect, text, Column
from sqlalchemy.schema import MetaData
from sqlalchemy import types as sqltypes
from sqlalchemy.exc import SQLAlchemyError

from core.logger import get_logger

logger = get_logger(__name__)


class SchemaMigrationError(Exception):
    """Raised when an automated schema synchronization fails."""
    pass


class SQLiteAutoMigrator:
    """
    Zero-dependency schema synchronization utility for SQLite.
    Dynamically diffs SQLAlchemy metadata against the active database
    and applies non-destructive 'ADD COLUMN' mutations.
    """

    # Pre-computed mapping of SQLAlchemy base types to safe SQLite defaults
    _TYPE_DEFAULTS: Dict[Type[sqltypes.TypeEngine], str] = {
        sqltypes.String: "''",
        sqltypes.Integer: "0",
        sqltypes.Boolean: "0",
        sqltypes.Float: "0.0",
        sqltypes.DateTime: "CURRENT_TIMESTAMP",
        sqltypes.Date: "CURRENT_DATE",
    }

    @classmethod
    def sync_schema(cls, engine: Engine, metadata: MetaData) -> None:
        """
        Inspects the live database and synchronizes missing columns defined in the ORM.

        Args:
            engine: SQLAlchemy engine bound to the SQLite database.
            metadata: Declarative metadata registry containing target schemas.

        Raises:
            SchemaMigrationError: If the DDL execution fails.
        """
        try:
            inspector = inspect(engine)
            existing_tables = set(inspector.get_table_names())

            for table_name, table_obj in metadata.tables.items():
                if table_name not in existing_tables:
                    # Table creation is handled upstream by metadata.create_all()
                    continue

                existing_columns = {col["name"] for col in inspector.get_columns(table_name)}

                for column in table_obj.columns:
                    if column.name not in existing_columns:
                        cls._append_column(engine, table_name, column)

        except SQLAlchemyError as e:
            logger.error(f"Fatal error during schema introspection: {str(e)}", exc_info=True)
            raise SchemaMigrationError(f"Failed to synchronize schema: {str(e)}") from e

    @classmethod
    def _resolve_default_value(cls, column: Column) -> str:
        """Pure function to determine a safe SQL default constraint string."""
        if column.nullable:
            return "NULL"

        for base_type, default_str in cls._TYPE_DEFAULTS.items():
            if isinstance(column.type, base_type):
                return default_str

        # Fallback for unrecognized non-nullable types to prevent syntax errors
        return "NULL"

    @classmethod
    def _append_column(cls, engine: Engine, table_name: str, column: Column) -> None:
        """Constructs and executes the ALTER TABLE statement."""
        default_val = cls._resolve_default_value(column)
        col_type_str = str(column.type.compile(engine.dialect))

        alter_stmt = f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type_str} DEFAULT {default_val}"
        logger.info(f"Schema Evolution | Executing DDL: {alter_stmt}")

        try:
            with engine.begin() as conn:
                conn.execute(text(alter_stmt))
            logger.info(f"Schema Evolution | Appended '{column.name}' to '{table_name}'.")
        except SQLAlchemyError as e:
            logger.error(f"Failed to mutate table '{table_name}': {str(e)}", exc_info=True)
            raise SchemaMigrationError(
                f"Migration constraint violation for {table_name}.{column.name}: {str(e)}"
            ) from e