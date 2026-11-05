"""Blocking S3 calls run in a thread; uploads use the spooled file, not bytes."""

from typing import BinaryIO

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

from upload_service.config import Settings


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            region_name=settings.region,
            config=Config(
                s3={"addressing_style": "path" if settings.path_style else "auto"},
                connect_timeout=5,
                read_timeout=30,
                retries={"mode": "standard", "max_attempts": 3},
            ),
        )

    def put(self, key: str, file: BinaryIO, content_type: str) -> None:
        file.seek(0)
        self.client.upload_fileobj(
            file,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
            Config=TransferConfig(use_threads=False),
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def ready(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)

    def close(self) -> None:
        self.client.close()
