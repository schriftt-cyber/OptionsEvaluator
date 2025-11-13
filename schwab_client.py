import os
from pathlib import Path

from schwab.auth import easy_client


def get_schwab_client():
    """
    Create and return a Schwab HTTP client using schwab-py.

    Secrets are pulled from environment variables so nothing sensitive
    is ever hard-coded into the repo.

    Required env vars:
      - SCHWAB_API_KEY      (your Schwab API key / client ID, e.g. 'XXXXX@SCHWAB')
      - SCHWAB_APP_SECRET   (your Schwab app secret)

    Optional:
      - SCHWAB_CALLBACK_URL (default: 'http://127.0.0.1:8080')
      - SCHWAB_TOKEN_PATH   (default: ~/.schwab/token.json)
    """
    # --- read env vars and give a clean error if missing ---
    missing = []
    api_key = os.environ.get("SCHWAB_API_KEY")
    app_secret = os.environ.get("SCHWAB_APP_SECRET")
    if not api_key:
        missing.append("SCHWAB_API_KEY")
    if not app_secret:
        missing.append("SCHWAB_APP_SECRET")

    if missing:
        raise RuntimeError(
            "Missing required Schwab environment variable(s): "
            + ", ".join(missing)
            + "\nSet them in Windows env vars or your PyCharm run configuration."
        )

    # IMPORTANT: callback URL must include an explicit port (e.g. :8080)
    # and must match exactly what you configured in the Schwab developer portal.
    callback_url = os.environ.get("SCHWAB_CALLBACK_URL") or "https://127.0.0.1:8080"

    # Token file goes OUTSIDE the repo by default
    default_token_path = Path("~/.schwab/token.json").expanduser()
    token_path = Path(os.environ.get("SCHWAB_TOKEN_PATH", str(default_token_path)))
    token_path.parent.mkdir(parents=True, exist_ok=True)

    client = easy_client(
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=str(token_path),
    )
    return client
