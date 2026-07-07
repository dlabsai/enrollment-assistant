"""Generate an alembic migration using a testcontainer PostgreSQL database."""

import os
import subprocess
import sys

import psycopg
from testcontainers.postgres import PostgresContainer


def main() -> None:
    """Start a PostgreSQL container and generate an alembic migration."""
    message = sys.argv[1] if len(sys.argv) > 1 else "auto_migration"

    print("Starting PostgreSQL container...")
    with PostgresContainer("pgvector/pgvector:pg17") as postgres:
        # Set environment variables for alembic
        os.environ["POSTGRES_SERVER"] = postgres.get_container_host_ip()
        os.environ["POSTGRES_PORT"] = str(postgres.get_exposed_port(5432))
        os.environ["POSTGRES_USER"] = postgres.username
        os.environ["POSTGRES_PASSWORD"] = postgres.password
        os.environ["POSTGRES_DB"] = postgres.dbname

        print(f"Container started at {os.environ['POSTGRES_SERVER']}:{os.environ['POSTGRES_PORT']}")

        # Create pgvector extension first
        print("Creating pgvector extension...")

        with psycopg.connect(
            host=os.environ["POSTGRES_SERVER"],
            port=os.environ["POSTGRES_PORT"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            dbname=os.environ["POSTGRES_DB"],
        ) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()

        print(f"Generating migration: {message}")
        result = subprocess.run(  # noqa: S603
            ["uv", "run", "alembic", "revision", "--autogenerate", "-m", message],  # noqa: S607
            check=False,
            cwd="/workspaces/demo-va/backend",
            capture_output=True,
            text=True,
        )

        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        if result.returncode != 0:
            print(f"Migration generation failed with code {result.returncode}")
            sys.exit(result.returncode)

        print("Migration generated successfully!")


if __name__ == "__main__":
    main()
