"""
FinGen v2 — Supabase client factory for Streamlit secrets.

Reads st.secrets and returns a synchronous Supabase client.
"""

import os
from typing import Any, Dict, Optional

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = Any  # type: ignore


def client_from_secrets(st_secrets: Optional[Dict[str, Any]] = None) -> Client:
    """
    Create a Supabase client from Streamlit secrets or environment.

    Expected secrets:
        SUPABASE_URL
        SUPABASE_ANON_KEY
        SUPABASE_SERVICE_KEY (optional, for server-side ops)
    """
    secrets = st_secrets or {}

    url = (
        secrets.get("SUPABASE_URL")
        or os.getenv("SUPABASE_URL")
        or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    )
    anon_key = (
        secrets.get("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    )

    if not url or not anon_key or create_client is None:
        return None

    try:
        return create_client(url, anon_key)
    except Exception:
        return None


def service_client_from_secrets(st_secrets: Optional[Dict[str, Any]] = None) -> Optional[Client]:
    """
    Create a Supabase client using the service role key.
    Use only for server-side operations (jobs, cache, storage, logs).
    """
    secrets = st_secrets or {}

    url = (
        secrets.get("SUPABASE_URL")
        or os.getenv("SUPABASE_URL")
        or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    )
    service_key = (
        secrets.get("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )

    if not url or not service_key or create_client is None:
        return None

    try:
        return create_client(url, service_key)
    except Exception:
        return None


def get_service_client() -> Optional[Client]:
    """Return a process-level service client (cached)."""
    global _service_client
    if _service_client is None:
        _service_client = service_client_from_secrets()
    return _service_client


_service_client: Optional[Client] = None