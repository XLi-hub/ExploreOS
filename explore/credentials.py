"""Read the explicitly configured model credential without exposing it to clients."""
import os
from scripts.cloud.runtime import ROOT


def model_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    path = ROOT / ".runtime/secrets/deepseek-api-key"
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError("Model credential file must be private (chmod 600) and not a symlink")
    return path.read_text(encoding="utf-8").strip() or None
