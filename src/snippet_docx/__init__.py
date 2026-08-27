"""snippet-docx: markdown snippet -> house-standard DOCX."""

from pathlib import Path

from dotenv import load_dotenv

# Load tool-specific .env file (repo convention: tools/{tool-name}/.env)
_tool_root = Path(__file__).parent.parent.parent
_env_file = _tool_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)
