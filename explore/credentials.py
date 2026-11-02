"""Private provider configuration. Public descriptors never contain credential material."""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from scripts.cloud.runtime import ROOT
from .store import Conflict

RELATIVE = ".runtime/service/private/provider.json"


def _path():
    folder = ROOT
    for part in (".runtime", "service", "private"):
        folder = folder / part
        if folder.is_symlink():
            raise RuntimeError("Provider configuration cannot use symlinked directories")
    return folder / "provider.json"


def _read_saved():
    path = _path()
    if not path.exists() and not path.is_symlink():
        return None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 8192:
                raise RuntimeError("Saved provider configuration must be a private regular file")
            raw = source.read(8193)
        value = json.loads(raw)
        if (not isinstance(value, dict) or not re.fullmatch(r"[a-f0-9]{32}", value.get("version", ""))
                or not _valid_key(value.get("api_key"))):
            raise ValueError
        return value
    except (OSError, ValueError, TypeError, UnicodeError):
        raise RuntimeError("Saved provider configuration is unreadable or invalid") from None


def _valid_key(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,256}", value) is not None


def _legacy_path():
    return ROOT / ".runtime/secrets/deepseek-api-key"


def model_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    saved = _read_saved()
    if saved:
        return saved["api_key"]
    path = _legacy_path()
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError("Model credential file must be private (chmod 600) and not a symlink")
    return path.read_text(encoding="utf-8").strip() or None


def public_configuration():
    """Passive, value-free metadata. Does not create files or contact the supplier."""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return {"credential_source": "environment", "credential_version": None, "credential_editable": False}
    saved = _read_saved()
    return {"credential_source": "local" if saved else "legacy" if _legacy_path().exists() else "missing",
            "credential_version": saved["version"] if saved else None, "credential_editable": True}


def configure(data):
    """The native HTTP owner gate authorizes callers; CLI runs as the local OS owner."""
    if not isinstance(data, dict) or data.get("operation") not in ("save", "remove"):
        raise ValueError("Choose save or remove for the local provider configuration")
    if "expected_version" not in data:
        raise ValueError("Refresh the provider configuration before changing it")
    expected = data["expected_version"]
    if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{32}", expected)):
        raise ValueError("Refresh the provider configuration before changing it")
    if os.environ.get("DEEPSEEK_API_KEY"):
        raise ValueError("The provider credential is managed by the environment; update it at its source")
    key = data.get("key")
    if data["operation"] == "save":
        key = key.strip() if isinstance(key, str) else None
        if not _valid_key(key):
            raise ValueError("Supply a single API credential of 16–256 ASCII letters, numbers, hyphens or underscores")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.stat().st_mode & 0o077:
        raise RuntimeError("The provider configuration directory must be private")
    lock_descriptor = os.open(path.parent / "provider.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_descriptor, "a") as lock:
        if os.fstat(lock.fileno()).st_mode & 0o077:
            raise RuntimeError("The provider configuration lock must be private")
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = _read_saved()
        if (saved["version"] if saved else None) != expected:
            raise Conflict("Provider configuration changed; refresh before saving again")
        if data["operation"] == "remove":
            if saved:
                path.unlink()
        else:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                                 prefix=".provider-", delete=False) as destination:
                    temporary = Path(destination.name)
                    os.chmod(temporary, 0o600)
                    json.dump({"version": uuid.uuid4().hex, "api_key": key}, destination)
                    destination.flush()
                    os.fsync(destination.fileno())
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return public_configuration()
