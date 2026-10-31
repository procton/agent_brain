"""Runtime configuration for the observatory backend and collector.

All runtime data (SQLite database, credentials, programmatically opened spool,
dashboard access code) lives in a platform-appropriate application data
directory, never inside the repository. Everything is overridable with
environment variables so tests can use temporary directories.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    """Platform-appropriate application data directory."""
    override = os.environ.get("OBSERVATORY_DATA_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "agent-brain-observatory"


@dataclass(frozen=True)
class Settings:
    """Process-wide settings, resolved once at startup."""

    data_dir: Path = field(default_factory=_default_data_dir)
    host: str = os.environ.get("OBSERVATORY_HOST", "127.0.0.1")
    port: int = int(os.environ.get("OBSERVATORY_PORT", "8000"))
    env: str = os.environ.get("OBSERVATORY_ENV", "development")

    # Ingestion limits (metadata-first: tiny payloads only).
    batch_max_events: int = 100
    batch_max_body_bytes: int = 512 * 1024

    # Browser dashboard session lifetime, in seconds.
    dashboard_session_ttl_seconds: int = 12 * 3600

    # Expertise-map decay: intensity halves this often while fading.
    expertise_decay_half_life_seconds: int = 20

    @property
    def production(self) -> bool:
        return self.env == "production"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "observatory.db"

    @property
    def credential_path(self) -> Path:
        """Local credential used by the collector to authenticate ingestion."""
        return self.data_dir / "collector_credential"

    @property
    def spool_dir(self) -> Path:
        return Path(os.environ.get("OBSERVATORY_SPOOL_DIR", str(self.data_dir / "spool")))

    @property
    def dashboard_code_path(self) -> Path:
        return self.data_dir / "dashboard_code"

    @property
    def frontend_dist_dir(self) -> Path:
        repo_root = Path(__file__).resolve().parents[2]
        return repo_root / "frontend" / "dist"

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Origins allowed to talk to the dashboard API from a browser.

        Loopback origins for the backend itself plus an explicit,
        development-only allowlist for the Vite dev server. Permissive CORS is
        never enabled; this list is only used to validate browser origins
        (same-origin requests usually carry no Origin header on GET).
        """
        origins: set[str] = set()
        for host in ("127.0.0.1", "localhost"):
            origins.add(f"http://{host}:{self.port}")
            origins.add(f"http://[::1]:{self.port}")
        if not self.production:
            dev_origins = os.environ.get(
                "OBSERVATORY_DEV_ORIGINS",
                "http://localhost:5173 http://127.0.0.1:5173 http://[::1]:5173",
            )
            origins.update(dev_origins.split())
        return frozenset(origins)


def create_credential_file(path: Path) -> str:
    """Create (idempotently) a local ingest credential and return the raw token.

    The file only ever contains the token itself, mode 0600.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        token = secret_from_file(path)
    except FileNotFoundError:
        token = os.urandom(32).hex()
        _write_private_file(path, token)
    return token


def secret_from_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError("credential file is empty")
    return raw


def _write_private_file(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    finally:
        _tighten_permissions(path)


def _tighten_permissions(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:  # pragma: no cover - e.g. unusual filesystems
        pass


def create_dashboard_code_file(path: Path) -> str:
    """Create (idempotently) the dashboard access code and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        code = secret_from_file(path)
    except FileNotFoundError:
        code = os.urandom(8).hex()  # short human-copyable code
        _write_private_file(path, code)
    return code


settings = Settings()
