"""Save a Claude API key into the project's private .env file and check that it works.

The key is typed without being shown, stored only in .env (which git ignores), and checked
with a free Models API lookup, so nothing is spent.
"""

from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

from app.config import get_settings

# The Docker launcher mounts the project's .env and points INSIGHTPULSE_ENV_FILE at it.
ENV_FILE = Path(
    os.environ.get("INSIGHTPULSE_ENV_FILE")
    or Path(os.path.abspath(__file__)).parent.parent / ".env"
)
MODEL = get_settings().llm_model


def save_key(key: str) -> None:
    """Replace any existing ANTHROPIC_API_KEY line in .env, keeping every other line."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    kept = [line for line in lines if not line.strip().startswith("ANTHROPIC_API_KEY=")]
    kept.append(f"ANTHROPIC_API_KEY={key}")
    ENV_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")


def check_key(key: str) -> tuple[bool, str]:
    """Ask Anthropic whether this key can use the app's model (free; no tokens used)."""
    import anthropic

    try:
        anthropic.Anthropic(api_key=key, max_retries=1, timeout=20).models.retrieve(MODEL)
    except anthropic.AuthenticationError:
        return False, "Anthropic rejected this key. Check you copied all of it."
    except anthropic.PermissionDeniedError:
        return False, "This key isn't allowed to use the model. Check your Console workspace."
    except anthropic.NotFoundError:
        return False, f"This account can't see the {MODEL} model."
    except anthropic.APIConnectionError:
        return True, "Saved, but Anthropic couldn't be reached to check it (no internet?)."
    return True, "Anthropic accepted the key."


def main() -> int:
    """Prompt for the key, save it and report whether it works."""
    print("\nPaste your Claude API key and press Enter.")
    print("(Nothing appears while you paste. That is normal.)\n")
    # Strip quotes, spaces and an invisible byte-order mark some terminals add when pasting.
    key = getpass("API key: ").replace("﻿", "").strip().strip('"').strip()
    if not key.startswith("sk-ant-") or len(key) < 30:
        print("\nThat doesn't look like a Claude API key (they start with sk-ant-). Nothing saved.")
        return 1
    ok, message = check_key(key)
    if not ok:
        print(f"\n{message} Nothing saved.")
        return 1
    save_key(key)
    print(f"\n{message}")
    print(f"Saved the key ending ...{key[-4:]} to the project's .env file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
