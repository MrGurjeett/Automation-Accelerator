"""
User API Client
Handles user-related API operations
"""
from api.base_api import BaseAPI
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class UserAPI(BaseAPI):
    """User API client for user-related endpoints"""

    def __init__(self, base_url: str):
        super().__init__(base_url)

    def create_user(self, user_data: Dict) -> Dict:
        """Create a new user"""
        logger.info(f"Creating user: {user_data.get('username')}")
        response = self.post("users", json_data=user_data)
        response.raise_for_status()
        return self.get_json_response(response)

    def get_user(self, user_id: str) -> Dict:
        """Get user by ID"""
        logger.info(f"Getting user: {user_id}")
        response = self.get(f"users/{user_id}")
        response.raise_for_status()
        return self.get_json_response(response)

    def update_user(self, user_id: str, user_data: Dict) -> Dict:
        """Update user information"""
        logger.info(f"Updating user: {user_id}")
        response = self.put(f"users/{user_id}", json_data=user_data)
        response.raise_for_status()
        return self.get_json_response(response)

    def delete_user(self, user_id: str) -> None:
        """Delete user by ID"""
        logger.info(f"Deleting user: {user_id}")
        response = self.delete(f"users/{user_id}")
        response.raise_for_status()

    def login(self, username: str, password: str) -> Dict:
        """Login and get authentication token"""
        logger.info(f"Logging in user: {username}")
        login_data = {"username": username, "password": password}
        response = self.post("auth/login", json_data=login_data)
        response.raise_for_status()
        json_response = self.get_json_response(response)
        
        # Set auth token if available
        if "token" in json_response:
            self.set_auth_token(json_response["token"])
        
        return json_response

    def get_user_list(self, page: int = 1, limit: int = 10) -> Dict:
        """Get list of users with pagination"""
        logger.info(f"Getting user list - Page: {page}, Limit: {limit}")
        params = {"page": page, "limit": limit}
        response = self.get("users", params=params)
        response.raise_for_status()
        return self.get_json_response(response)
