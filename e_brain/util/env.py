import os
from pathlib import Path


def load_dotenv_if_present(path: str | None = None) -> None:
    """Load a simple .env file if present without external deps.

    Supports `KEY=VALUE` lines and ignores comments and blanks.
    Does not override existing environment variables.
    """
    env_path = Path(path) if path else Path.cwd() / ".env"
    if not env_path.exists():
        return
    try:
        with env_path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if "=" not in s:
                    continue
                key, value = s.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except Exception:
        # Fail silent; this is a convenience loader
        pass

