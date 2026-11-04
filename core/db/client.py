"""
FinGen v2 — Supabase Client Singleton
"""

import os
import logging
from typing import Optional, Any

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = Any  # type: ignore

logger = logging.getLogger(__name__)

_client: Optional[Client] = None
_service_client: Optional[Client] = None


def get_supabase_client(use_service_key: bool = False) -> Client:
    """
    Get or create Supabase client singleton.
    
    Args:
        use_service_key: If True, use service role key (bypasses RLS).
                        Should only be used for server-side operations (jobs, cache, admin).
    
    Returns:
        Supabase client
    """
    global _client, _service_client
    
    if create_client is None:
        raise RuntimeError("The 'supabase' package is not installed. Install via 'pip install supabase'.")

    if use_service_key:
        if _service_client is None:
            url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
            key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            if not url or not key:
                raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment")
            _service_client = create_client(url, key)
            logger.info("Supabase service client initialized")
        return _service_client
    else:
        if _client is None:
            url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
            key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
            if not url or not key:
                raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment")
            _client = create_client(url, key)
            logger.info("Supabase anon client initialized")
        return _client


def get_user_client(access_token: str) -> Client:
    """
    Create a client bound to a specific user's access token (for RLS).
    Use this in request handlers after user authentication.
    """
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    if not url:
        raise RuntimeError("SUPABASE_URL must be set")
    client = create_client(url, os.getenv("SUPABASE_ANON_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY"))
    client.auth.set_session(access_token, "")
    return client