import os
import boto3
from botocore.client import Config
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def upload_to_bucket(file_path: str) -> Optional[str]:
    """
    Uploads a local file to the configured S3-compatible bucket.
    Returns the public URL of the uploaded file, or None if failed.
    """
    bucket = os.getenv("BUCKET")
    endpoint = os.getenv("ENDPOINT")
    secret_key = os.getenv("SECRET_ACCESS_KEY")
    # Supports common Access Key ID environment names
    access_key = (
        os.getenv("AWS_ACCESS_KEY_ID") or 
        os.getenv("ACCESS_KEY") or 
        os.getenv("ACCESS_KEY_ID") or 
        os.getenv("KEY") or
        os.getenv("PGUSER")  # Fallback just in case
    )
    region = os.getenv("REGION", "us-east-1")
    
    if not bucket or not endpoint or not secret_key:
        logger.warning("Bucket (S3) configuration is incomplete in environment variables.")
        return None
        
    try:
        # Format endpoint URL if it doesn't have scheme
        if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
            endpoint = "https://" + endpoint
            
        s3 = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version='s3v4'),
            region_name=region
        )
        
        file_name = os.path.basename(file_path)
        
        # Try to upload file
        logger.info(f"Uploading {file_name} to bucket {bucket} via {endpoint}...")
        try:
            s3.upload_file(file_path, bucket, file_name, ExtraArgs={'ACL': 'public-read'})
        except Exception as acl_err:
            logger.warning(f"Upload with public-read ACL failed, trying without ACL: {acl_err}")
            s3.upload_file(file_path, bucket, file_name)
            
        # Construct public URL
        if endpoint.endswith('/'):
            public_url = f"{endpoint}{bucket}/{file_name}"
        else:
            public_url = f"{endpoint}/{bucket}/{file_name}"
            
        logger.info(f"Successfully uploaded to bucket: {public_url}")
        return public_url
    except Exception as e:
        logger.error(f"S3 upload error for {file_path}: {e}")
        return None
