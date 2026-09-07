import os

from dotenv import load_dotenv

load_dotenv()


def get_required_environment(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value

    raise RuntimeError(
        f"Missing required environment variable: {name}. "
        "Copy .env-example to .env and configure it for this environment."
    )


def get_database_url() -> str:
    return get_required_environment("DATABASE_URL")
