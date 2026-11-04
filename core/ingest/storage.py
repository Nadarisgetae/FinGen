"""
FinGen v2 — Ingestion Layer (adapted from CaseGen)
Changes from CaseGen:
- Files upload to Supabase Storage, not local disk
- Spreadsheet parser outputs Fact rows directly (bypasses chunker)
- Chunker used ONLY for narrative text
- docling_parser: added parse_pdf_bytes for Storage downloads
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def upload_to_storage(supabase, bucket: str, path: str, data: bytes, content_type: str = None) -> str:
    """Upload bytes to Supabase Storage. Returns storage path."""
    supabase.storage.from_(bucket).upload(path, data, {"content-type": content_type} if content_type else {})
    return path


def get_signed_url(supabase, bucket: str, path: str, expires_in: int = 3600) -> str:
    """Get a signed download URL for a private Storage object."""
    result = supabase.storage.from_(bucket).create_signed_url(path, expires_in)
    return result.signed_url if hasattr(result, "signed_url") else result["signedUrl"]


def parse_storage_path(user_id, document_id: str, filename: str) -> str:
    """Build canonical storage path: uploads/{user_id}/{document_id}/{filename}"""
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")[:120]
    return f"uploads/{user_id}/{document_id}/{safe_name}"
