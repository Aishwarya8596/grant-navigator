"""Launch local ADK Web with the project's model setting explicitly applied."""

import argparse
import os
from pathlib import Path
import sys

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", help="Override the model in grant_navigator/.env")
    args = parser.parse_args()
    values = dotenv_values(PROJECT_ROOT / "grant_navigator" / ".env")
    model = args.model or values.get("GRANT_NAVIGATOR_MODEL") or DEFAULT_MODEL
    environment = os.environ.copy()
    environment["GRANT_NAVIGATOR_MODEL"] = model
    adk = Path(sys.executable).parent / "adk"
    if not adk.exists():
        parser.error("ADK is not installed in this environment. Run uv sync first.")
    print(f"Grant Navigator model: {model}", flush=True)
    os.chdir(PROJECT_ROOT)
    os.execve(
        adk,
        [str(adk), "web", "--host", "127.0.0.1", "--port", str(args.port), str(PROJECT_ROOT)],
        environment,
    )


if __name__ == "__main__":
    main()
