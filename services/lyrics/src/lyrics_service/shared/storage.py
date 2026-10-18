"""S3 access: RustFS locally, real S3 in production (where the endpoint and
keys are not set and boto3 uses the ECS task role)."""

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class ObjectNotFound(Exception):
    pass


class ObjectTooLarge(Exception):
    pass


class S3Storage:
    """Blocking boto3 calls: the worker runs them in a thread (asyncio.to_thread)."""

    def __init__(
        self, *, bucket: str, endpoint_url: str | None, region: str, force_path_style: bool
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            config=Config(
                s3={"addressing_style": "path" if force_path_style else "auto"},
                connect_timeout=5,
                read_timeout=30,
                retries={"mode": "standard", "max_attempts": 3},
            ),
        )

    def read(self, key: str, max_bytes: int) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectNotFound(f"S3 object {key} does not exist") from exc
            raise
        body = response["Body"]
        try:
            if response["ContentLength"] > max_bytes:
                raise ObjectTooLarge(
                    f"S3 object {key} is {response['ContentLength']} bytes; "
                    f"the limit is {max_bytes}"
                )
            data = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(data) > max_bytes:
            raise ObjectTooLarge(f"S3 object {key} is larger than {max_bytes} bytes")
        return data
