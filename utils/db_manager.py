"""
Database Manager
Handles database connections and operations
"""
import logging
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manage database connections and operations"""

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.connection = None
        self.cursor = None

    def connect(self) -> None:
        """Establish database connection"""
        try:
            self.connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            self.cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            logger.info(f"Connected to database: {self.database}")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def disconnect(self) -> None:
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        logger.info("Database connection closed")

    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query"""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            
            results = self.cursor.fetchall()
            logger.info(f"Query executed successfully. Rows returned: {len(results)}")
            return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            raise

    def execute_update(self, query: str, params: tuple = None) -> int:
        """Execute an INSERT, UPDATE, or DELETE query"""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            
            self.connection.commit()
            rows_affected = self.cursor.rowcount
            logger.info(f"Update executed successfully. Rows affected: {rows_affected}")
            return rows_affected
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Update execution failed: {e}")
            raise

    def fetch_one(self, query: str, params: tuple = None) -> Optional[Dict[str, Any]]:
        """Fetch a single row"""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            
            result = self.cursor.fetchone()
            return dict(result) if result else None
        except Exception as e:
            logger.error(f"Fetch one failed: {e}")
            raise

    def verify_record_exists(self, table: str, conditions: Dict[str, Any]) -> bool:
        """Verify if a record exists"""
        where_clause = " AND ".join([f"{k} = %s" for k in conditions.keys()])
        query = f"SELECT COUNT(*) as count FROM {table} WHERE {where_clause}"
        
        result = self.fetch_one(query, tuple(conditions.values()))
        exists = result['count'] > 0 if result else False
        
        logger.info(f"Record exists check: {exists}")
        return exists

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
