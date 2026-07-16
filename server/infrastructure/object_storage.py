from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable


class ObjectStorageUnavailable(RuntimeError):
    pass


class UnavailableObjectStorageSigner:
    def create_download_url(self, object_key: str) -> tuple[str, datetime]:
        raise ObjectStorageUnavailable("Object storage is not configured")


class S3ObjectStorageSigner:
    def __init__(self, client: Any, bucket: str, ttl_seconds: int = 900) -> None:
        if not bucket or ttl_seconds <= 0:
            raise ValueError("S3 bucket and positive URL TTL are required")
        self._client = client
        self._bucket = bucket
        self._ttl_seconds = ttl_seconds

    def create_download_url(self, object_key: str) -> tuple[str, datetime]:
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": object_key},
                ExpiresIn=self._ttl_seconds,
            )
        except Exception as error:
            raise ObjectStorageUnavailable("Unable to sign model download") from error
        return url, datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)


def create_s3_signer(
    *,
    endpoint: str,
    region: str | None,
    bucket: str,
    access_key: str,
    secret_key: str,
    ttl_seconds: int,
    client_factory: Callable[..., Any] | None = None,
) -> S3ObjectStorageSigner:
    if client_factory is None:
        try:
            import boto3
        except ImportError as error:
            raise ObjectStorageUnavailable("boto3 server extra is not installed") from error
        client_factory = boto3.client
    client = client_factory(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    return S3ObjectStorageSigner(client, bucket, ttl_seconds)
