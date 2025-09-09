# app.py — FAC Cloud Run (Eventarc GCS → DocAI) + non-PDF handling
from __future__ import annotations

import os
import json
import hashlib
import logging
import mimetypes
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from google.cloud import storage
from google.cloud import documentai_v1 as documentai  # pip: google-cloud-documentai
from PIL import Image  # pip: Pillow

# ------------------------------------------------------------------------------
# Config / Env
# ------------------------------------------------------------------------------
SCHEMA = "fac.docai.v1"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DOC_PRC_NAME = os.getenv("DOC_PRC_NAME", "")  # e.g. projects/123/locations/eu/processors/xxxx
DOC_PRC_LOC = os.getenv("DOC_PRC_LOC", "eu")  # optional (for logs)
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "")  # where JSONs are written

# Non-PDF strategy: convert / reject / skip
NONPDF_STRATEGY = os.getenv("NONPDF_STRATEGY", "convert").lower()
MAX_IMAGE_MB = float(os.getenv("MAX_IMAGE_MB", "20"))  # guard rail for huge images

IMAGE_CTYPES = {"image/png", "image/jpeg", "image/tiff"}

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("fac")

# ------------------------------------------------------------------------------
# Clients
# ------------------------------------------------------------------------------
_gcs = storage.Client()

@lru_cache(maxsize=1)
def _docai_client() -> documentai.DocumentProcessorServiceClient:
    return documentai.DocumentProcessorServiceClient()

def _docai() -> documentai.DocumentProcessorServiceClient:
    return _docai_client()

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _sha256(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def _safe_get(d: Dict[str, Any], *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def _normalized_value_to_py(v: Optional[documentai.Document.Entity.NormalizedValue]) -> Any:
    if not v:
        return None
    # Try common fields first
    if getattr(v, "text", None):
        return v.text
    if getattr(v, "money_value", None):
        m = v.money_value
        try:
            currency = getattr(m, "currency_code", "") or ""
            units = getattr(m, "units", 0)
            nanos = getattr(m, "nanos", 0)
            return {"currency": currency, "amount": float(units) + nanos / 1e9}
        except Exception:
            return str(m)
    if getattr(v, "date_value", None):
        dv = v.date_value
        # Document AI's date_value has year/month/day fields
        return {"year": dv.year, "month": dv.month, "day": dv.day}
    if getattr(v, "datetime_value", None):
        return str(v.datetime_value)
    return None

def _entity_to_ann(e: documentai.Document.Entity) -> Dict[str, Any]:
    # Normalize a DocAI entity
    kind = getattr(e, "type_", None) or getattr(e, "type", None) or "unknown"
    conf = getattr(e, "confidence", None)

    text = getattr(e, "mention_text", None)
    value = _normalized_value_to_py(getattr(e, "normalized_value", None)) or text

    page = None
    try:
        pa = getattr(e, "page_anchor", None)
        if pa and getattr(pa, "page_refs", None):
            pr = pa.page_refs[0]
            page = int(getattr(pr, "page", 0))
    except Exception:
        page = None

    return {
        "kind": kind,
        "text": text,
        "value": value,
        "confidence": conf,
        "page": page,
    }

def _collect_languages(doc: documentai.Document) -> List[str]:
    langs: Dict[str, float] = {}
    try:
        for p in getattr(doc, "pages", []) or []:
            for dl in getattr(p, "detected_languages", []) or []:
                code = getattr(dl, "language_code", None)
                conf = float(getattr(dl, "confidence", 0.0) or 0.0)
                if code:
                    langs[code] = max(langs.get(code, 0.0), conf)
    except Exception:
        pass
    return sorted(langs, key=langs.get, reverse=True)[:3]

def _image_to_pdf_bytes(b: bytes) -> bytes:
    """Convert (PNG/JPEG/TIFF) to single or multipage PDF bytes."""
    with BytesIO(b) as src:
        with Image.open(src) as im:
            # Handle mode
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            out = BytesIO()
            try:
                # Try multipage TIFF
                frames = [im]
                try:
                    im.seek(0)
                    while True:
                        im.seek(im.tell() + 1)
                        frames.append(im.copy())
                except EOFError:
                    pass
                if len(frames) > 1:
                    frames[0].save(out, format="PDF", save_all=True, append_images=frames[1:])
                else:
                    frames[0].save(out, format="PDF")
            finally:
                out.seek(0)
            return out.read()

def _save_reject(bucket: str, name: str, ctype: str, blob_size: Optional[int],
                 reason: str, extra: Dict[str, Any] | None = None) -> None:
    if not OUTPUT_BUCKET:
        log.error(json.dumps({"phase":"write-output","err":"OUTPUT_BUCKET not set"}))
        return
    out_key = f"rejects/v1/{name}.json"
    out = {
        "schema": "fac.reject.v1",
        "created_at": _now_iso(),
        "source": {
            "bucket": bucket, "name": name,
            "content_type": ctype, "size": blob_size
        },
        "reason": reason,
        "extra": extra or {},
        "output": {"bucket": OUTPUT_BUCKET, "key": out_key},
    }
    _gcs.bucket(OUTPUT_BUCKET).blob(out_key).upload_from_string(
        json.dumps(out, ensure_ascii=False), content_type="application/json"
    )
    log.info(json.dumps({"phase":"nonpdf-reject","ok":True,"url":f"gs://{OUTPUT_BUCKET}/{out_key}"}))

# ------------------------------------------------------------------------------
# FastAPI
# ------------------------------------------------------------------------------
app = FastAPI()

@app.get("/")
def root_ok():
    return JSONResponse({"ok": True})

@app.get("/healthz")
def healthz():
    return JSONResponse({"ok": True})

# Eventarc (GCS) sends POST / (binary CloudEvents)
@app.post("/")
async def events(request: Request):
    # CloudEvent headers (for trace)
    ce_type = request.headers.get("ce-type")
    ce_id   = request.headers.get("ce-id")
    ce_src  = request.headers.get("ce-source")

    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        log.error(json.dumps({"phase":"bad-request","err":"invalid-json"}))
        return Response(status_code=204)

    bucket = _safe_get(body, "bucket") or _safe_get(body, "bucket", "name")
    name   = _safe_get(body, "name")
    ctype  = _safe_get(body, "contentType")

    if not bucket or not name:
        log.error(json.dumps({"phase":"bad-request","err":"missing bucket/name"}))
        return Response(status_code=204)

    # Download object
    try:
        blob = _gcs.bucket(bucket).blob(name)
        content = blob.download_as_bytes()
        blob_size = blob.size
        blob_generation = blob.generation
    except Exception as e:
        log.error(json.dumps({"phase":"gcs-download-error","bucket":bucket,"name":name,"err":str(e)}))
        return Response(status_code=204)

    # Determine content-type if missing
    ctype = ctype or mimetypes.guess_type(name)[0] or "application/octet-stream"

    # Prepare DocAI input (handle non-PDF)
    doc_bytes: bytes
    preprocess_info: Optional[Dict[str, Any]] = None

    if ctype != "application/pdf":
        size_mb = (len(content) if content else (blob_size or 0)) / (1024 * 1024)
        if NONPDF_STRATEGY == "skip":
            log.info(json.dumps({"phase":"skip-nonpdf","name":name,"contentType":ctype}))
            return Response(status_code=204)

        if NONPDF_STRATEGY == "reject" or ctype not in IMAGE_CTYPES or size_mb > MAX_IMAGE_MB:
            _save_reject(
                bucket=bucket, name=name, ctype=ctype, blob_size=blob_size,
                reason="unsupported-nonpdf",
                extra={"content_type": ctype, "size_mb": round(size_mb, 3), "strategy": NONPDF_STRATEGY}
            )
            return Response(status_code=204)

        # convert → PDF
        try:
            pdf_bytes = _image_to_pdf_bytes(content)
            doc_bytes = pdf_bytes
            preprocess_info = {
                "converted_from": ctype,
                "bytes_in": len(content),
                "bytes_out": len(pdf_bytes),
            }
            log.info(json.dumps({
                "phase":"nonpdf-convert","from":ctype,"bytes_in":len(content),"bytes_out":len(pdf_bytes)
            }))
        except Exception as e:
            log.error(json.dumps({"phase":"nonpdf-convert-error","err":str(e)}))
            _save_reject(bucket=bucket, name=name, ctype=ctype, blob_size=blob_size,
                         reason="convert-failed", extra={"error": str(e), "content_type": ctype})
            return Response(status_code=204)
    else:
        doc_bytes = content

    # DocAI call
    if not DOC_PRC_NAME:
        log.error(json.dumps({"phase":"docai-misconfig","err":"DOC_PRC_NAME not set"}))
        return Response(status_code=204)

    try:
        req = {
            "name": DOC_PRC_NAME,
            "raw_document": {
                "content": doc_bytes,
                "mime_type": "application/pdf"
            },
        }
        result = _docai().process_document(request=req)
        doc: documentai.Document = result.document

        # Languages
        langs = _collect_languages(doc)

        # Annotations
        annotations: List[Dict[str, Any]] = []
        for e in (getattr(doc, "entities", []) or []):
            try:
                annotations.append(_entity_to_ann(e))
            except Exception as ex:
                log.error(json.dumps({"phase":"entity-normalize-error","err":str(ex)}))

        # Derived picks
        def pick_first(k: str) -> Optional[Dict[str, Any]]:
            hits = [a for a in annotations if a.get("kind") == k and a.get("value") is not None]
            return hits[0] if hits else None

        derived: Dict[str, Any] = {}
        for k in ["invoice_number", "vendor_name", "total_amount", "invoice_date", "currency"]:
            hit = pick_first(k)
            if hit:
                v = hit.get("value")
                if k == "total_amount":
                    try:
                        v = float(str(v).replace(",", ""))
                    except Exception:
                        pass
                derived[k] = {"value": v, "confidence": hit.get("confidence")}

        # Output JSON
        if not OUTPUT_BUCKET:
            log.error(json.dumps({"phase":"write-output","err":"OUTPUT_BUCKET not set"}))
            return Response(status_code=204)

        num_pages = len(getattr(doc, "pages", []) or [])
        text_len  = len(getattr(doc, "text", "") or "")

        out_key = f"docai-json/v1/{name}.json"
        out: Dict[str, Any] = {
            "schema": SCHEMA,
            "created_at": _now_iso(),
            "source": {
                "bucket": bucket, "name": name, "generation": blob_generation,
                "size": blob_size, "content_type": ctype, "sha256": _sha256(content)
            },
            "event": {"ce_type": ce_type, "ce_id": ce_id, "ce_source": ce_src},
            "processor": {"name": DOC_PRC_NAME, "location": DOC_PRC_LOC, "version": "unknown"},
            "document": {"pages": num_pages, "text_len": text_len, "languages": langs},
            "annotations": annotations,
            "derived": derived,
            "output": {"bucket": OUTPUT_BUCKET, "key": out_key},
            "errors": []
        }
        if preprocess_info:
            out["preprocess"] = preprocess_info

        _gcs.bucket(OUTPUT_BUCKET).blob(out_key).upload_from_string(
            json.dumps(out, ensure_ascii=False), content_type="application/json"
        )
        log.info(json.dumps({"phase":"write-output","ok":True,"url":f"gs://{OUTPUT_BUCKET}/{out_key}"}))

    except Exception as e:
        log.error(json.dumps({"phase":"docai-error","err":str(e)}))

    # Always return 204 to prevent retries
    return Response(status_code=204)