"""
Base API Module
Contains the BaseAPI class with common API operations
"""
import requests
import logging
from typing import Dict, Optional, Any
import json

logger = logging.getLogger(__name__)


class BaseAPI:
    """Base class for all API clients"""

    def __init__(self, base_url: str, timeout: int = 30, headers: Optional[Dict] = None):
        self.base_url = base_url
        self.timeout = timeout
        self.default_headers = headers or {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.session = requests.Session()
        self.session.headers.update(self.default_headers)

    def _log_request(self, method: str, url: str, **kwargs) -> None:
        """Log API request details"""
        logger.info(f"API Request: {method} {url}")
        if kwargs.get('json'):
            logger.debug(f"Request Body: {json.dumps(kwargs['json'], indent=2)}")
        if kwargs.get('params'):
            logger.debug(f"Request Params: {kwargs['params']}")

    def _log_response(self, response: requests.Response) -> None:
        """Log API response details"""
        logger.info(f"API Response: {response.status_code}")
        try:
            logger.debug(f"Response Body: {json.dumps(response.json(), indent=2)}")
        except Exception:
            logger.debug(f"Response Body: {response.text}")

    def get(self, endpoint: str, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> requests.Response:
        """Send GET request"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        merged_headers = {**self.default_headers, **(headers or {})}
        
        self._log_request("GET", url, params=params)
        response = self.session.get(url, params=params, headers=merged_headers, timeout=self.timeout)
        self._log_response(response)
        
        return response

    def post(self, endpoint: str, json_data: Optional[Dict] = None, 
             data: Optional[Any] = None, headers: Optional[Dict] = None) -> requests.Response:
        """Send POST request"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        merged_headers = {**self.default_headers, **(headers or {})}
        
        self._log_request("POST", url, json=json_data, data=data)
        response = self.session.post(url, json=json_data, data=data, 
                                     headers=merged_headers, timeout=self.timeout)
        self._log_response(response)
        
        return response

    def put(self, endpoint: str, json_data: Optional[Dict] = None, 
            data: Optional[Any] = None, headers: Optional[Dict] = None) -> requests.Response:
        """Send PUT request"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        merged_headers = {**self.default_headers, **(headers or {})}
        
        self._log_request("PUT", url, json=json_data, data=data)
        response = self.session.put(url, json=json_data, data=data, 
                                    headers=merged_headers, timeout=self.timeout)
        self._log_response(response)
        
        return response

    def patch(self, endpoint: str, json_data: Optional[Dict] = None, 
              headers: Optional[Dict] = None) -> requests.Response:
        """Send PATCH request"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        merged_headers = {**self.default_headers, **(headers or {})}
        
        self._log_request("PATCH", url, json=json_data)
        response = self.session.patch(url, json=json_data, 
                                      headers=merged_headers, timeout=self.timeout)
        self._log_response(response)
        
        return response

    def delete(self, endpoint: str, headers: Optional[Dict] = None) -> requests.Response:
        """Send DELETE request"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        merged_headers = {**self.default_headers, **(headers or {})}
        
        self._log_request("DELETE", url)
        response = self.session.delete(url, headers=merged_headers, timeout=self.timeout)
        self._log_response(response)
        
        return response

    def set_auth_token(self, token: str, token_type: str = "Bearer") -> None:
        """Set authentication token in headers"""
        self.session.headers["Authorization"] = f"{token_type} {token}"
        logger.info(f"Auth token set: {token_type} {'*' * 10}")

    def clear_auth_token(self) -> None:
        """Clear authentication token"""
        if "Authorization" in self.session.headers:
            del self.session.headers["Authorization"]
        logger.info("Auth token cleared")

    def verify_status_code(self, response: requests.Response, expected_code: int) -> bool:
        """Verify response status code"""
        actual_code = response.status_code
        if actual_code == expected_code:
            logger.info(f"Status code verification passed: {actual_code}")
            return True
        else:
            logger.error(f"Status code mismatch. Expected: {expected_code}, Got: {actual_code}")
            return False

    def get_json_response(self, response: requests.Response) -> Dict:
        """Get JSON response body"""
        try:
            return response.json()
        except Exception as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise
