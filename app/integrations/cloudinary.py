from __future__ import annotations

import asyncio
import io
import logging
import uuid

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class BlobStorage:
    """Encrypted payload store. Cloudinary is used when configured; local demo files stay encrypted."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cloud_enabled = bool(
            not settings.local_demo_mode
            and settings.cloudinary_cloud_name
            and settings.cloudinary_api_key
            and settings.cloudinary_api_secret
        )
        self.http = httpx.AsyncClient(timeout=45, follow_redirects=True)
        if not self.cloud_enabled:
            self.settings.local_blob_dir.mkdir(parents=True, exist_ok=True)
        provider = "Cloudinary" if self.cloud_enabled else "local demo/development storage"
        logger.info("File storage configured: %s", provider)
        if self.cloud_enabled:
            import cloudinary

            cloudinary.config(
                cloud_name=settings.cloudinary_cloud_name,
                api_key=settings.cloudinary_api_key,
                api_secret=settings.cloudinary_api_secret,
                secure=True,
            )

    async def put(self, encrypted_bytes: bytes, *, content_type: str = "application/octet-stream") -> str:
        key = uuid.uuid4().hex
        if self.cloud_enabled:
            import cloudinary.uploader

            result = await asyncio.to_thread(
                cloudinary.uploader.upload,
                io.BytesIO(encrypted_bytes),
                public_id=f"secureshare/{key}",
                resource_type="raw",
                type="authenticated",
                overwrite=False,
                context={"content_type": content_type},
            )
            return "cloudinary:" + result["public_id"]
        path = self.settings.local_blob_dir / f"{key}.blob"
        await asyncio.to_thread(path.write_bytes, encrypted_bytes)
        return "local:" + key

    async def get(self, storage_key: str) -> bytes:
        provider, _, key = storage_key.partition(":")
        if provider == "local":
            return await asyncio.to_thread((self.settings.local_blob_dir / f"{key}.blob").read_bytes)
        if provider != "cloudinary" or not self.cloud_enabled:
            raise FileNotFoundError("Stored file is unavailable")
        import cloudinary.utils
        url, _ = cloudinary.utils.cloudinary_url(key, resource_type="raw", type="authenticated", sign_url=True, secure=True)
        response = await self.http.get(url)
        response.raise_for_status()
        return response.content

    async def delete(self, storage_key: str) -> None:
        provider, _, key = storage_key.partition(":")
        if provider == "local":
            path = self.settings.local_blob_dir / f"{key}.blob"
            try:
                await asyncio.to_thread(path.unlink)
            except FileNotFoundError:
                pass
        elif provider == "cloudinary" and self.cloud_enabled:
            import cloudinary.uploader

            await asyncio.to_thread(cloudinary.uploader.destroy, key, resource_type="raw", type="authenticated", invalidate=True)

    async def close(self) -> None:
        await self.http.aclose()
