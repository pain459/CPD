"""Minimal S3 helper (boto3, path-style addressing for S3 clones like RustFS).

Shared by api + worker: both Dockerfiles COPY shared/s3util.py.
Keep this file dependency-light (boto3 only).
"""
import os

import boto3
import botocore
from botocore.client import Config


def settings():
    return {
        "endpoint": os.getenv("S3_ENDPOINT", "http://s3:9000"),
        "access_key": os.getenv("S3_ACCESS_KEY", "cpdadmin"),
        "secret_key": os.getenv("S3_SECRET_KEY", "cpd_s3_dev_password_change_me"),
        "bucket": os.getenv("S3_BUCKET", "cpd-raw"),
    }


def client(endpoint=None, access_key=None, secret_key=None):
    s = settings()
    return boto3.client(
        "s3",
        endpoint_url=endpoint or s["endpoint"],
        aws_access_key_id=access_key or s["access_key"],
        aws_secret_access_key=secret_key or s["secret_key"],
        region_name="us-east-1",
        config=Config(
            s3={"addressing_style": "path"},  # required: bucket-in-host fails vs IP:port
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=60,
        ),
    )


def ensure_bucket(cli, bucket: str):
    try:
        cli.create_bucket(Bucket=bucket)
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise


def key_for(job_id: str, filename: str) -> str:
    safe = (filename or "upload").replace("/", "_").replace("\\", "_")
    return f"raw/{job_id}/{safe}"


def put_file(cli, bucket: str, key: str, path):
    cli.upload_file(str(path), bucket, key)


def download_file(cli, bucket: str, key: str, dest):
    cli.download_file(bucket, key, str(dest))


def get_bytes(cli, bucket: str, key: str) -> bytes:
    obj = cli.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()
