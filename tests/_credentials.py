"""Ephemeral credentials for temporary test databases, never real accounts."""
import secrets

TEST_PASSWORD = secrets.token_urlsafe(24)
