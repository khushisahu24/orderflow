"""Create the two local users if they are not already there.

Run from the project folder after migrations:

    .\.venv\Scripts\python.exe scripts\seed.py

Passwords come from ORDERFLOW_ADMIN_PASSWORD and ORDERFLOW_STAFF_PASSWORD.
This script refuses to write to a database whose name starts with orderflow_test.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config import get_settings
from app.db import build_engine, build_session_factory
from app.models import User
from app.security import hash_password


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    settings = get_settings()
    database_name = settings.database_url.rsplit("/", 1)[-1]
    if database_name.startswith("orderflow_test"):
        raise SystemExit("Refusing to seed a test database.")

    engine = build_engine(settings.database_url, settings.db_connect_timeout_seconds)
    session = build_session_factory(engine)()
    try:
        users = (
            ("admin@orderflow.example", "admin", "ORDERFLOW_ADMIN_PASSWORD"),
            ("staff@orderflow.example", "staff", "ORDERFLOW_STAFF_PASSWORD"),
        )
        for email, role, variable in users:
            password = os.environ.get(variable)
            if not password:
                raise SystemExit(f"Set {variable} before seeding.")
            existing = session.scalars(select(User).where(User.email == email)).one_or_none()
            if existing is None:
                session.add(
                    User(
                        email=email,
                        password_hash=hash_password(password, settings.bcrypt_rounds),
                        role=role,
                        is_active=True,
                    )
                )
                print(f"created {role}: {email}")
            else:
                print(f"already present: {email}")
        session.commit()
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
