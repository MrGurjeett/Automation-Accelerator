"""
Excel Utilities
Helper functions for working with Excel files
"""
import logging
from typing import List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class ExcelUtils:
    """Utilities for Excel file operations"""

    @staticmethod
    def read_excel(file_path: str, sheet_name: str = None) -> List[Dict[str, Any]]:
        """Read data from Excel file"""
        try:
            import pandas as pd
            
            if sheet_name:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(file_path)
            
            # Convert NaN to None
            df = df.where(pd.notna(df), None)
            
            data = df.to_dict('records')
            logger.info(f"Read {len(data)} rows from: {file_path}")
            return data
        except ImportError:
            logger.error("pandas not installed. Install with: pip install pandas openpyxl")
            raise
        except Exception as e:
            logger.error(f"Error reading Excel: {e}")
            raise

    @staticmethod
    def write_excel(data: List[Dict[str, Any]], file_path: str, sheet_name: str = "Sheet1") -> None:
        """Write data to Excel file"""
        try:
            import pandas as pd
            
            df = pd.DataFrame(data)
            df.to_excel(file_path, sheet_name=sheet_name, index=False)
            logger.info(f"Written {len(data)} rows to: {file_path}")
        except ImportError:
            logger.error("pandas not installed. Install with: pip install pandas openpyxl")
            raise
        except Exception as e:
            logger.error(f"Error writing Excel: {e}")
            raise

    @staticmethod
    def get_sheet_names(file_path: str) -> List[str]:
        """Get all sheet names from Excel file"""
        try:
            import pandas as pd
            
            excel_file = pd.ExcelFile(file_path)
            sheet_names = excel_file.sheet_names
            logger.info(f"Sheet names: {sheet_names}")
            return sheet_names
        except ImportError:
            logger.error("pandas not installed. Install with: pip install pandas openpyxl")
            raise
        except Exception as e:
            logger.error(f"Error getting sheet names: {e}")
            raise

    @staticmethod
    def update_excel(file_path: str, updates: Dict[str, Any], 
                    row_identifier: str, identifier_value: Any, 
                    sheet_name: str = None) -> None:
        """Update specific rows in Excel file"""
        try:
            import pandas as pd
            
            # Read existing data
            if sheet_name:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(file_path)
            
            # Update rows
            mask = df[row_identifier] == identifier_value
            for column, value in updates.items():
                df.loc[mask, column] = value
            
            # Write back
            df.to_excel(file_path, sheet_name=sheet_name or "Sheet1", index=False)
            logger.info(f"Updated Excel file: {file_path}")
        except Exception as e:
            logger.error(f"Error updating Excel: {e}")
            raise

    @staticmethod
    def append_to_excel(file_path: str, new_data: List[Dict[str, Any]], 
                       sheet_name: str = None) -> None:
        """Append new data to existing Excel file"""
        try:
            import pandas as pd
            
            # Read existing data
            if Path(file_path).exists():
                if sheet_name:
                    df_existing = pd.read_excel(file_path, sheet_name=sheet_name)
                else:
                    df_existing = pd.read_excel(file_path)
                
                # Append new data
                df_new = pd.DataFrame(new_data)
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            else:
                df_combined = pd.DataFrame(new_data)
            
            # Write back
            df_combined.to_excel(file_path, sheet_name=sheet_name or "Sheet1", index=False)
            logger.info(f"Appended {len(new_data)} rows to: {file_path}")
        except Exception as e:
            logger.error(f"Error appending to Excel: {e}")
            raise
