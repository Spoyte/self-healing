"""
Pytest configuration and fixtures.
"""

import pytest


@pytest.fixture
def sample_data():
    """Provide sample data for tests."""
    return {
        'test': 'data',
        'number': 42
    }
