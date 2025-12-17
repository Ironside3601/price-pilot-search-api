"""
Unit tests for Search API - Core functionality tests.

Tests the main endpoints and error handling.
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock the Secret Manager before importing search_api
with patch('google.cloud.secretmanager.SecretManagerServiceClient') as mock_client:
    mock_instance = MagicMock()
    mock_response = MagicMock()
    mock_response.payload.data.decode.return_value = 'fake-secret-value'
    mock_instance.access_secret_version.return_value = mock_response
    mock_client.return_value = mock_instance
    
    from search_api import app

client = TestClient(app)


# Mock Google Custom Search API responses
@pytest.fixture(autouse=True)
def mock_google_search():
    """Mock Google Custom Search API to avoid real API calls."""
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            'items': [
                {
                    'title': 'Test Product',
                    'link': 'https://example.com/product',
                    'snippet': 'Test description'
                }
            ]
        })
        mock_get.return_value.__aenter__.return_value = mock_response
        yield mock_get


class TestHealthCheck:
    """Test health check endpoint."""
    
    def test_health_check(self):
        """Health check should return 200 with status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert "status" in response.json()


class TestRetailersEndpoint:
    """Test retailers list endpoint."""
    
    def test_get_retailers(self):
        """Should return list of retailers."""
        response = client.get("/retailers")
        assert response.status_code == 200
        data = response.json()
        assert "retailers" in data
        assert isinstance(data["retailers"], list)
        assert len(data["retailers"]) > 0


class TestSearchEndpoint:
    """Test search endpoint core functionality."""
    
    def test_search_with_valid_input(self):
        """Search with valid input should return 200."""
        payload = {
            "searchQuery": "laptop",
            "productTitle": "Dell XPS 13"
        }
        response = client.post("/search", json=payload)
        assert response.status_code == 200
        assert "results" in response.json()
    
    def test_search_missing_search_query(self):
        """Search without searchQuery should fail."""
        payload = {
            "productTitle": "Dell XPS 13"
        }
        response = client.post("/search", json=payload)
        assert response.status_code == 422
    
    def test_search_missing_product_title(self):
        """Search without productTitle should still work (it's optional)."""
        payload = {
            "searchQuery": "laptop"
        }
        response = client.post("/search", json=payload)
        assert response.status_code == 200
        assert "results" in response.json()
    
    def test_search_with_special_characters(self):
        """Search with special characters should work."""
        payload = {
            "searchQuery": "laptop & computer (gaming)",
            "productTitle": 'Dell XPS 13" @ $999'
        }
        response = client.post("/search", json=payload)
        assert response.status_code == 200
    
    def test_search_with_unicode(self):
        """Search with unicode characters should work."""
        payload = {
            "searchQuery": "笔记本电脑",
            "productTitle": "ラップトップ"
        }
        response = client.post("/search", json=payload)
        assert response.status_code == 200


class TestErrorHandling:
    """Test error cases."""
    
    def test_invalid_endpoint(self):
        """Invalid endpoint should return 404."""
        response = client.get("/invalid-endpoint")
        assert response.status_code == 404
    
    def test_search_method_not_allowed(self):
        """GET /search should not be allowed."""
        response = client.get("/search")
        assert response.status_code == 405


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
