"""The start-up log never shows the password of GRAVITYLAN_DATABASE_URL."""
import pytest


@pytest.mark.parametrize("url, expected", [
    ("postgresql+asyncpg://gravity:s3cret@db:5432/gravitylan", "postgresql+asyncpg://gravity:***@db:5432/gravitylan"),
    ("sqlite+aiosqlite:////app/data/gravitylan.db", "sqlite+aiosqlite:////app/data/gravitylan.db"),
])
def test_database_url_in_the_start_up_log_hides_the_password(url, expected):
    from app.main import _loggable_database_url
    assert _loggable_database_url(url) == expected
