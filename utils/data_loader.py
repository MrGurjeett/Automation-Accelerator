"""
Data Loader
Loads test data from various sources (YAML, JSON, Excel)
"""
import yaml
import json
from pathlib import Path
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class DataLoader:
    """Load test data from various formats"""

    @staticmethod
    def load_yaml(file_path: str) -> Dict[str, Any]:
        """Load data from YAML file"""
        try:
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)
            logger.info(f"YAML data loaded from: {file_path}")
            return data
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML: {e}")
            raise

    @staticmethod
    def load_json(file_path: str) -> Dict[str, Any]:
        """Load data from JSON file"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            logger.info(f"JSON data loaded from: {file_path}")
            return data
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON: {e}")
            raise

    @staticmethod
    def load_excel(file_path: str, sheet_name: str = None) -> List[Dict[str, Any]]:
        """Load data from Excel file"""
        try:
            import pandas as pd
            
            if sheet_name:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(file_path)
            
            data = df.to_dict('records')
            logger.info(f"Excel data loaded from: {file_path}")
            return data
        except ImportError:
            logger.error("pandas not installed. Install with: pip install pandas openpyxl")
            raise
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
        except Exception as e:
            logger.error(f"Error loading Excel: {e}")
            raise

    @staticmethod
    def load_csv(file_path: str) -> List[Dict[str, Any]]:
        """Load data from CSV file"""
        try:
            import csv
            
            data = []
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                data = list(reader)
            
            logger.info(f"CSV data loaded from: {file_path}")
            return data
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
        except Exception as e:
            logger.error(f"Error loading CSV: {e}")
            raise

    @staticmethod
    def get_test_data(data_key: str, data_file: str = "config/testdata/sample_data.yaml") -> Any:
        """Get specific test data by key"""
        file_ext = Path(data_file).suffix.lower()
        
        if file_ext == '.yaml' or file_ext == '.yml':
            data = DataLoader.load_yaml(data_file)
        elif file_ext == '.json':
            data = DataLoader.load_json(data_file)
        else:
            logger.error(f"Unsupported file format: {file_ext}")
            raise ValueError(f"Unsupported file format: {file_ext}")
        
        # Support dot notation for nested keys
        keys = data_key.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    logger.warning(f"Key not found: {data_key}")
                    return None
            else:
                logger.warning(f"Invalid path: {data_key}")
                return None
        
        return value
