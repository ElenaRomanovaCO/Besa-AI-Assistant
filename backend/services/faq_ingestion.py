"""FAQ file ingestion: S3 upload and Bedrock Knowledge Base sync."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class SyncStatus(str, Enum):
    PENDING = "PENDING"
    SYNCING = "SYNCING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class FAQSyncResult:
    success: bool
    entry_count: int
    sync_job_id: Optional[str]
    status: SyncStatus
    error_message: Optional[str] = None


class FAQIngestionService:
    """
    Handles raw FAQ file upload to S3 and triggering Bedrock Knowledge Base sync.
    Bedrock handles chunking and embedding natively — no file parsing required.
    """

    def __init__(
        self,
        s3_bucket: str,
        knowledge_base_id: str,
        data_source_id: str,
        metadata_table_name: str,
        region: str = "us-east-1",
    ):
        self._bucket = s3_bucket
        self._knowledge_base_id = knowledge_base_id
        self._data_source_id = data_source_id
        self._s3 = boto3.client("s3", region_name=region)
        self._bedrock_agent = boto3.client("bedrock-agent", region_name=region)
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(metadata_table_name)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def file_exists(self, filename: str) -> bool:
        """Check if faq/{filename} already exists in S3."""
        try:
            self._s3.head_object(Bucket=self._bucket, Key=f"faq/{filename}")
            return True
        except ClientError:
            return False

    def upload_file(
        self,
        raw_content: bytes,
        filename: str,
        uploaded_by: str = "admin",
    ) -> FAQSyncResult:
        """Upload raw file to S3 as faq/{filename} and trigger Bedrock sync."""
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=f"faq/{filename}",
                Body=raw_content,
                ContentType="text/markdown",
                Metadata={"uploaded-by": uploaded_by},
            )
            logger.info("Uploaded faq/%s to s3://%s", filename, self._bucket)
        except ClientError as e:
            logger.error("S3 upload failed: %s", e)
            return FAQSyncResult(
                success=False,
                entry_count=0,
                sync_job_id=None,
                status=SyncStatus.FAILED,
                error_message=f"S3 upload error: {e}",
            )

        sync_job_id = None
        try:
            sync_job_id = self._trigger_bedrock_sync()
        except Exception as e:
            logger.error("Bedrock sync trigger failed: %s", e)

        status = SyncStatus.SYNCING if sync_job_id else SyncStatus.FAILED
        self._update_metadata(
            sync_job_id=sync_job_id,
            status=status,
            uploaded_by=uploaded_by,
        )
        return FAQSyncResult(
            success=sync_job_id is not None,
            entry_count=0,
            sync_job_id=sync_job_id,
            status=status,
        )

    def list_files(self) -> list[dict]:
        """List all files under the faq/ prefix with S3 metadata."""
        try:
            response = self._s3.list_objects_v2(
                Bucket=self._bucket, Prefix="faq/"
            )
            files = []
            for obj in response.get("Contents", []):
                key = obj["Key"]
                filename = key[len("faq/"):]
                if not filename:
                    continue  # skip the faq/ prefix entry itself
                try:
                    head = self._s3.head_object(Bucket=self._bucket, Key=key)
                    uploaded_by = head.get("Metadata", {}).get("uploaded-by", "")
                except Exception:
                    uploaded_by = ""
                files.append({
                    "filename": filename,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "uploaded_by": uploaded_by,
                })
            return files
        except ClientError as e:
            logger.error("Failed to list faq/ objects: %s", e)
            return []

    def delete_file(self, filename: str) -> bool:
        """Delete faq/{filename} from S3 and trigger a Bedrock re-sync."""
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=f"faq/{filename}")
            logger.info("Deleted faq/%s from s3://%s", filename, self._bucket)
        except ClientError as e:
            logger.error("Failed to delete faq/%s: %s", filename, e)
            return False

        try:
            sync_job_id = self._trigger_bedrock_sync()
            self._update_metadata(
                sync_job_id=sync_job_id,
                status=SyncStatus.SYNCING,
                uploaded_by="admin",
            )
        except Exception as e:
            logger.error("Bedrock sync after delete failed: %s", e)

        return True

    def get_sync_status(self) -> dict:
        """Check current sync status; polls Bedrock if a sync job is in progress."""
        try:
            response = self._table.get_item(
                Key={"config_id": "faq_metadata", "sk": "latest"}
            )
            item = response.get("Item", {})
            if not item:
                return {"status": "NO_DATA"}

            status = item.get("status", SyncStatus.PENDING.value)
            sync_job_id = item.get("sync_job_id", "")

            if status == SyncStatus.SYNCING.value and sync_job_id:
                live_status = self._poll_bedrock_job(sync_job_id)
                if live_status != status:
                    item["status"] = live_status
                    self._table.update_item(
                        Key={"config_id": "faq_metadata", "sk": "latest"},
                        UpdateExpression="SET #s = :s",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={":s": live_status},
                    )

            return {
                "status": item.get("status"),
                "sync_job_id": sync_job_id,
                "last_updated": item.get("last_updated"),
                "uploaded_by": item.get("uploaded_by"),
            }
        except Exception as e:
            logger.error("Error fetching sync status: %s", e)
            return {"status": "ERROR", "error": str(e)}

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _trigger_bedrock_sync(self) -> str:
        """Start a Bedrock Knowledge Base ingestion job and return the job ID."""
        response = self._bedrock_agent.start_ingestion_job(
            knowledgeBaseId=self._knowledge_base_id,
            dataSourceId=self._data_source_id,
        )
        job_id = response["ingestionJob"]["ingestionJobId"]
        logger.info("Bedrock KB sync started: job_id=%s", job_id)
        return job_id

    def _update_metadata(
        self,
        sync_job_id: Optional[str],
        status: SyncStatus,
        uploaded_by: str,
    ) -> None:
        """Write FAQ sync metadata to DynamoDB."""
        try:
            self._table.put_item(
                Item={
                    "config_id": "faq_metadata",
                    "sk": "latest",
                    "sync_job_id": sync_job_id or "",
                    "status": status.value,
                    "uploaded_by": uploaded_by,
                    "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
        except ClientError as e:
            logger.error("Failed to update FAQ metadata in DynamoDB: %s", e)

    def _poll_bedrock_job(self, job_id: str) -> str:
        """Query Bedrock for ingestion job status."""
        try:
            response = self._bedrock_agent.get_ingestion_job(
                knowledgeBaseId=self._knowledge_base_id,
                dataSourceId=self._data_source_id,
                ingestionJobId=job_id,
            )
            bedrock_status = response["ingestionJob"]["status"]
            mapping = {
                "COMPLETE": SyncStatus.COMPLETED.value,
                "FAILED": SyncStatus.FAILED.value,
                "STARTING": SyncStatus.SYNCING.value,
                "IN_PROGRESS": SyncStatus.SYNCING.value,
            }
            return mapping.get(bedrock_status, SyncStatus.SYNCING.value)
        except Exception as e:
            logger.error("Error polling Bedrock job %s: %s", job_id, e)
            return SyncStatus.SYNCING.value
