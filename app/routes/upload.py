"""Upload routes for client file transfers."""
import os
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from .auth import get_current_active_user
from ..config import get_settings
from ..services.websocket import websocket_manager

router = APIRouter(prefix="/api/upload", tags=["upload"])
logger = logging.getLogger(__name__)

# Stream uploads to disk in chunks rather than buffering the whole file in RAM.
_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB
# Reject uploads larger than this (configurable via env). 0 disables the limit.
_MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024


@router.post("/audio")
async def upload_audio(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Upload audio file to ingest directory."""
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    
    # Log client connection (automatically goes to console, file, and WebSocket)
    logger.info(f"📤 Client upload: {current_user.username} @ {client_ip}")
    
    # Sanitize the client-supplied filename to its basename only. Without this,
    # a name like "../../etc/cron.d/evil.mp3" would escape the queue directory.
    safe_name = Path(file.filename or "").name
    if not safe_name or safe_name in (".", ".."):
        logger.warning(f"❌ Invalid filename from {current_user.username}: {file.filename!r}")
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Validate file extension
    allowed_extensions = settings.config.watchdog_client.extensions
    file_ext = Path(safe_name).suffix.lower()

    if file_ext not in allowed_extensions:
        logger.warning(f"❌ Invalid file type from {current_user.username}: {safe_name}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
        )

    # Save directly to queue (client already handled stability)
    try:
        queue_dir = settings.ingest_dir / "queue"
        queue_dir.mkdir(exist_ok=True)

        queue_path = queue_dir / safe_name

        # Handle duplicate filenames
        counter = 1
        original_stem = Path(safe_name).stem
        while queue_path.exists():
            queue_path = queue_dir / f"{original_stem}_{counter}{file_ext}"
            counter += 1

        # Stream to disk in chunks to avoid loading the whole file into memory,
        # enforcing the configured size limit as we go.
        bytes_written = 0
        try:
            with open(queue_path, "wb") as f:
                while True:
                    chunk = await file.read(_UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if _MAX_UPLOAD_BYTES and bytes_written > _MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File too large (limit {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
                        )
                    f.write(chunk)
        except BaseException:
            # Don't leave a partial/oversized file behind in the queue.
            queue_path.unlink(missing_ok=True)
            raise

        file_size_mb = bytes_written / (1024 * 1024)

        logger.info(f"✅ Uploaded: {queue_path.name} ({file_size_mb:.2f} MB) from {current_user.username} @ {client_ip}")
        
        return {
            "message": "File uploaded successfully",
            "filename": queue_path.name,
            "size_mb": round(file_size_mb, 2),
            "path": str(queue_path)
        }
        
    except HTTPException:
        # Preserve intentional client errors (e.g. 413 too large) instead of
        # masking them as a generic 500.
        raise
    except Exception as e:
        logger.error(f"❌ Upload failed from {current_user.username} @ {client_ip}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.get("/status")
async def upload_status(
    request: Request,
    current_user: User = Depends(get_current_active_user)
):
    """Get upload endpoint status."""
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    
    logger.info(f"🔌 Client connected: {current_user.username} @ {client_ip}")
    await websocket_manager.send_log(
        f"🔌 Client connected: {current_user.username} @ {client_ip}",
        level="info"
    )
    
    from .. import __version__
    return {
        "online": True,
        "ingest_directory": str(settings.ingest_dir),
        "allowed_extensions": settings.config.watchdog_client.extensions,
        "server_version": __version__
    }
