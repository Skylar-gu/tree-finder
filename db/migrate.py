"""Runnable migration entrypoint: python -m db.migrate"""

from .repository import migrate

if __name__ == "__main__":
    migrate()
    print("migrations applied")
