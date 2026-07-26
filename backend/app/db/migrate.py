from __future__ import annotations

from app.db.connection import configured_database_backend
from app.db.migrations import initialize_default_database


def main() -> None:
    initialize_default_database()
    print(f"database migrations completed ({configured_database_backend()})")


if __name__ == "__main__":
    main()
