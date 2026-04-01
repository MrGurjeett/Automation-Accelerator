"""
API Test Module
Tests for API endpoints
"""
from __future__ import annotations

import pytest
from api.user_api import UserAPI
from utils.config_loader import get_config
import logging

logger = logging.getLogger(__name__)


pytestmark = pytest.mark.api


@pytest.fixture
def user_api():
    """Create UserAPI instance"""
    config = get_config()
    env_config = config.get_environment_config()
    api_url = env_config.get("api_url", "https://api.example.com")
    return UserAPI(api_url)


class TestUserAPI:
    """Test cases for User API"""

    def test_create_user(self, user_api):
        """Test creating a new user"""
        user_data = {
            "username": "testuser@example.com",
            "password": "Test@123",
            "first_name": "Test",
            "last_name": "User"
        }
        
        response = user_api.create_user(user_data)
        
        assert "id" in response, "Response should contain user ID"
        assert response["username"] == user_data["username"]
        
        logger.info("Test create user - PASSED")

    def test_get_user(self, user_api):
        """Test getting user by ID"""
        user_id = "12345"
        
        response = user_api.get_user(user_id)
        
        assert response["id"] == user_id
        
        logger.info("Test get user - PASSED")

    def test_login(self, user_api):
        """Test user login"""
        username = "testuser@example.com"
        password = "Test@123"
        
        response = user_api.login(username, password)
        
        assert "token" in response, "Response should contain auth token"
        
        logger.info("Test login - PASSED")

    def test_get_user_list(self, user_api):
        """Test getting user list with pagination"""
        response = user_api.get_user_list(page=1, limit=10)
        
        assert "users" in response or isinstance(response, list)
        
        logger.info("Test get user list - PASSED")

    def test_update_user(self, user_api):
        """Test updating user information"""
        user_id = "12345"
        update_data = {
            "first_name": "Updated",
            "last_name": "Name"
        }
        
        response = user_api.update_user(user_id, update_data)
        
        assert response["first_name"] == update_data["first_name"]
        
        logger.info("Test update user - PASSED")

    def test_delete_user(self, user_api):
        """Test deleting a user"""
        user_id = "12345"
        
        user_api.delete_user(user_id)
        
        # If no exception raised, deletion was successful
        logger.info("Test delete user - PASSED")
