"""
Configuration Loader
Loads and manages configuration from YAML files
"""
import yaml
from pathlib import Path
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Load and manage configuration"""

    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = Path(config_path)
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Configuration loaded from: {self.config_path}")
            return config
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML: {e}")
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key (supports dot notation)"""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        
        return value

    def get_environment_config(self, env: str = None) -> Dict[str, Any]:
        """Get environment-specific configuration"""
        if env is None:
            env = self.get('environment', 'qa')
        
        return self.get(f'environments.{env}', {})

    def get_browser_config(self) -> Dict[str, Any]:
        """Get browser configuration"""
        return self.get('browser', {})

    def get_test_config(self) -> Dict[str, Any]:
        """Get test configuration"""
        return self.get('test', {})

    def get_database_config(self) -> Dict[str, Any]:
        """Get database configuration"""
        return self.get('database', {})

    def get_email_config(self) -> Dict[str, Any]:
        """Get email configuration"""
        return self.get('email', {})

    def get_api_config(self) -> Dict[str, Any]:
        """Get API configuration"""
        return self.get('api', {})

    def reload_config(self) -> None:
        """Reload configuration from file"""
        self.config = self.load_config()
        logger.info("Configuration reloaded")


# Singleton instance
_config_instance = None


def get_config(config_path: str = "config/config.yaml") -> ConfigLoader:
    """Get singleton configuration instance"""
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigLoader(config_path)
    return _config_instance
