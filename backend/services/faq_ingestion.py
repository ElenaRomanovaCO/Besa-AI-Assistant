"""FAQ file ingestion: S3 upload and Bedrock Knowledge Base sync."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from backend.models.faq_models import FAQEntry, FAQFileParser

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
    Handles FAQ file upload to S3 and triggering Bedrock Knowledge Base sync.
    Stores sync metadata in DynamoDB for status polling.
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
        self._metadata_table = metadata_table_name
        self._s3 = boto3.client("s3", region_name=region)
        self._bedrock_agent = boto3.client("bedrock-agent", region_name=region)
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(metadata_table_name)

    def upload_and_sync(
        self,
        file_content: bytes,
        file_format: str,
        uploaded_by: str = "admin",
    ) -> FAQSyncResult:
        """
        Parse FAQ file, upload to S3, trigger Bedrock KB sync, record metadata.
        """
        # Parse and validate
        try:
            text_content = file_content.decode("utf-8")
            entries = FAQFileParser.parse(text_content, file_format)
        except Exception as e:
            return FAQSyncResult(
                success=False,
                entry_count=0,
                sync_job_id=None,
                status=SyncStatus.FAILED,
                error_message=f"Parse error: {e}",
            )

        validation_errors = FAQFileParser.validate(entries)
        if validation_errors:
            return FAQSyncResult(
                success=False,
                entry_count=len(entries),
                sync_job_id=None,
                status=SyncStatus.FAILED,
                error_message=f"Validation errors: {'; '.join(validation_errors[:5])}",
            )

        if not entries:
            return FAQSyncResult(
                success=False,
                entry_count=0,
                sync_job_id=None,
                status=SyncStatus.FAILED,
                error_message="No FAQ entries found in file.",
            )

        # Upload each entry as a separate markdown file to S3
        # (Bedrock KB ingests files from the S3 prefix)
        upload_id = str(uuid.uuid4())[:8]
        try:
            self._upload_entries_to_s3(entries, upload_id)
        except Exception as e:
            logger.error("S3 upload failed: %s", e)
            return FAQSyncResult(
                success=False,
                entry_count=len(entries),
                sync_job_id=None,
                status=SyncStatus.FAILED,
                error_message=f"S3 upload error: {e}",
            )

        # Trigger Bedrock Knowledge Base sync
        try:
            sync_job_id = self._trigger_bedrock_sync()
        except Exception as e:
            logger.error("Bedrock sync trigger failed: %s", e)
            sync_job_id = None

        # Record metadata in DynamoDB
        status = SyncStatus.SYNCING if sync_job_id else SyncStatus.FAILED
        self._update_metadata(
            entry_count=len(entries),
            sync_job_id=sync_job_id,
            status=status,
            uploaded_by=uploaded_by,
        )

        return FAQSyncResult(
            success=sync_job_id is not None,
            entry_count=len(entries),
            sync_job_id=sync_job_id,
            status=status,
        )

    def _upload_entries_to_s3(self, entries: list[FAQEntry], upload_id: str) -> None:
        """Upload FAQ entries as individual markdown files under faq/ prefix."""
        # First, delete existing FAQ files (replace strategy)
        self._clear_faq_prefix()

        for entry in entries:
            key = f"faq/{entry.id}.md"
            content = entry.to_markdown().encode("utf-8")
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType="text/markdown",
                Metadata={
                    "entry-id": entry.id,
                    "upload-id": upload_id,
                    "category": entry.category,
                },
            )
        logger.info("Uploaded %d FAQ entries to s3://%s/faq/", len(entries), self._bucket)

    def _clear_faq_prefix(self) -> None:
        """Delete all objects under faq/ prefix (replace on upload)."""
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix="faq/"):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                self._s3.delete_objects(
                    Bucket=self._bucket, Delete={"Objects": objects}
                )

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
        entry_count: int,
        sync_job_id: Optional[str],
        status: SyncStatus,
        uploaded_by: str,
    ) -> None:
        """Write FAQ sync metadata to DynamoDB."""
        try:
            self._table.put_item(
                Item={
                    "pk": "faq_metadata",
                    "sk": "latest",
                    "entry_count": entry_count,
                    "sync_job_id": sync_job_id or "",
                    "status": status.value,
                    "uploaded_by": uploaded_by,
                    "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
        except ClientError as e:
            logger.error("Failed to update FAQ metadata in DynamoDB: %s", e)

    def get_sync_status(self) -> dict:
        """
        Check current sync status. Polls Bedrock if a sync job is in progress.
        """
        try:
            response = self._table.get_item(
                Key={"pk": "faq_metadata", "sk": "latest"}
            )
            item = response.get("Item", {})
            if not item:
                return {"status": "NO_DATA", "entry_count": 0}

            status = item.get("status", SyncStatus.PENDING.value)
            sync_job_id = item.get("sync_job_id", "")

            # Poll Bedrock for live status if job is in progress
            if status == SyncStatus.SYNCING.value and sync_job_id:
                live_status = self._poll_bedrock_job(sync_job_id)
                if live_status != status:
                    item["status"] = live_status
                    self._table.update_item(
                        Key={"pk": "faq_metadata", "sk": "latest"},
                        UpdateExpression="SET #s = :s",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={":s": live_status},
                    )

            return {
                "status": item.get("status"),
                "entry_count": int(item.get("entry_count", 0)),
                "sync_job_id": sync_job_id,
                "last_updated": item.get("last_updated"),
                "uploaded_by": item.get("uploaded_by"),
            }
        except Exception as e:
            logger.error("Error fetching sync status: %s", e)
            return {"status": "ERROR", "error": str(e)}

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

    def generate_presigned_upload_url(
        self, file_format: str, expiry_seconds: int = 300
    ) -> str:
        """Generate a presigned S3 URL for direct browser uploads."""
        key = f"uploads/faq-upload-{int(time.time())}.{file_format}"
        url = self._s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ContentType": "application/octet-stream",
            },
            ExpiresIn=expiry_seconds,
        )
        return url
