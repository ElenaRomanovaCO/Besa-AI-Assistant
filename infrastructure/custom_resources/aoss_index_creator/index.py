"""Custom Resource Lambda: Creates the vector index in OpenSearch Serverless.

Bedrock Knowledge Base requires the index to exist before the KB resource
can be created. CloudFormation has no native AOSS index resource, so this
Custom Resource fills the gap.

Called by CDK custom_resources.Provider on Create/Update/Delete events.
"""

import datetime
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── SigV4 helpers ────────────────────────────────────────────────────────────

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _build_headers(
    method: str,
    host: str,
    path: str,
    body_bytes: bytes,
    region: str,
    credentials,
) -> dict:
    """Return HTTP headers with AWS SigV4 auth for the AOSS service."""
    service = "aoss"
    content_type = "application/json"
    payload_hash = hashlib.sha256(body_bytes).hexdigest()

    t = datetime.datetime.utcnow()
    amz_date = t.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = t.strftime("%Y%m%d")

    # Build sorted canonical headers (lowercase keys required by SigV4)
    canon = {
        "content-type": content_type,
        "host": host,
        "x-amz-date": amz_date,
    }
    if credentials.token:
        canon["x-amz-security-token"] = credentials.token

    sorted_items = sorted(canon.items())
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted_items)
    signed_headers = ";".join(k for k, _ in sorted_items)

    canonical_request = "\n".join([
        method, path, "", canonical_headers, signed_headers, payload_hash,
    ])

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    sig_key = _signing_key(credentials.secret_key, date_stamp, region, service)
    signature = hmac.new(
        sig_key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    auth = (
        f"{algorithm} "
        f"Credential={credentials.access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    headers = {
        "Content-Type": content_type,
        "X-Amz-Date": amz_date,
        "Authorization": auth,
    }
    if credentials.token:
        headers["X-Amz-Security-Token"] = credentials.token
    return headers


# ── Index definition ──────────────────────────────────────────────────────────

# Titan Text Embeddings v2 produces 1024-dim vectors by default.
# Field names must match storage_stack.py field_mapping config.
INDEX_BODY = json.dumps({
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 512,
        }
    },
    "mappings": {
        "properties": {
            "bedrock-knowledge-base-default-vector": {
                "type": "knn_vector",
                "dimension": 1024,
                "method": {
                    "name": "hnsw",
                    "engine": "faiss",
                    "space_type": "l2",
                    "parameters": {
                        "ef_construction": 512,
                        "m": 16,
                    },
                },
            },
            "AMAZON_BEDROCK_TEXT_CHUNK": {"type": "text", "index": True},
            "AMAZON_BEDROCK_METADATA": {"type": "text", "index": False},
        }
    },
})


# ── Core logic ────────────────────────────────────────────────────────────────

def _create_index(collection_endpoint: str, index_name: str, region: str) -> str:
    host = collection_endpoint.replace("https://", "").rstrip("/")
    path = f"/{index_name}"
    body_bytes = INDEX_BODY.encode("utf-8")

    creds = boto3.Session().get_credentials().get_frozen_credentials()
    headers = _build_headers("PUT", host, path, body_bytes, region, creds)

    url = f"https://{host}{path}"
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method="PUT")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = resp.read().decode("utf-8")
            logger.info("Index created: %s", result)
            return result
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        logger.warning("HTTPError %s: %s", exc.code, body)
        if exc.code == 400 and "resource_already_exists_exception" in body.lower():
            logger.info("Index already exists — OK")
            return "already_exists"
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


# ── Lambda handler (CDK cr.Provider protocol) ─────────────────────────────────

# AOSS data access policies take up to ~90s to propagate after creation.
_INITIAL_WAIT_SECS = 60   # wait before first attempt
_MAX_RETRIES = 5          # total attempts
_RETRY_WAIT_SECS = 30     # wait between retries on 403


def handler(event, context):
    logger.info("Event: %s", json.dumps(event))
    props = event["ResourceProperties"]
    collection_endpoint = props["CollectionEndpoint"]
    index_name = props["IndexName"]
    region = props["Region"]

    request_type = event["RequestType"]

    if request_type in ("Create", "Update"):
        logger.info(
            "Sleeping %ds to allow AOSS data access policy to propagate...",
            _INITIAL_WAIT_SECS,
        )
        time.sleep(_INITIAL_WAIT_SECS)

        last_err = None
        for attempt in range(_MAX_RETRIES):
            try:
                _create_index(collection_endpoint, index_name, region)
                return {"PhysicalResourceId": f"{collection_endpoint}/{index_name}"}
            except RuntimeError as exc:
                last_err = exc
                if "403" in str(exc) and attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "403 on attempt %d/%d — AOSS policy still propagating. "
                        "Retrying in %ds...",
                        attempt + 1, _MAX_RETRIES, _RETRY_WAIT_SECS,
                    )
                    time.sleep(_RETRY_WAIT_SECS)
                else:
                    break

        raise last_err  # all retries exhausted

    # Delete — leave index in place (KB may still reference it during rollback)
    return {"PhysicalResourceId": event.get("PhysicalResourceId", index_name)}
