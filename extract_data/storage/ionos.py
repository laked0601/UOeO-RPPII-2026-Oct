"""
The IONOS remote storage (an S3-compatible bucket) where the PDFs and their OCR text are kept.

Layout inside the bucket (one pair of files per filing):
    accounts/pdf/<filing_id>.pdf     the original accounts PDF
    accounts/txt/<filing_id>.txt     the OCR text of it

The access key and secret key are never written in the code: they are read from the
environment variables IONOS_BUCKET_ACCESS_KEY and IONOS_BUCKET_SECRET_KEY.
"""

import boto3
import os

BUCKET = "uoeo-rpp2-2026-oct-dev"
REGION = "eu-central-3"  # Berlin
ENDPOINT = "https://s3.eu-central-3.ionoscloud.com"
ACCESS_KEY_VAR = "IONOS_BUCKET_ACCESS_KEY"
SECRET_KEY_VAR = "IONOS_BUCKET_SECRET_KEY"


def object_keys(filing_id):
    """The bucket keys of a filing's (pdf, txt) files.  S3 keys have no leading slash."""
    return f"accounts/pdf/{filing_id}.pdf", f"accounts/txt/{filing_id}.txt"


def make_client():
    """An S3 client for the IONOS bucket, using the keys from the environment."""
    access_key, secret_key = os.environ.get(ACCESS_KEY_VAR), os.environ.get(SECRET_KEY_VAR)
    if not access_key or not secret_key:
        raise RuntimeError(f"Set the environment variables {ACCESS_KEY_VAR} and {SECRET_KEY_VAR} "
                           "to the bucket's access key and secret key.")
    return boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION,
                        aws_access_key_id=access_key, aws_secret_access_key=secret_key)


def upload_file(client, path, key, content_type):
    """Upload the local file `path` to `key` in the bucket (an existing object is replaced)."""
    client.upload_file(str(path), BUCKET, key, ExtraArgs={"ContentType": content_type})
