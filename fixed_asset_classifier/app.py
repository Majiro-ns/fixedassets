import os, json, logging, sys, mimetypes
from fastapi import FastAPI, Request, Response
from google.api_core.client_options import ClientOptions
from google.cloud import documentai as documentai
from google.cloud import storage
from google.protobuf.json_format import MessageToDict  # 追加
import hashlib, datetime
from typing import List, Dict

SCHEMA = "fac.docai.v1"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("fac")

DOC_PRC_NAME = os.getenv("DOC_PRC_NAME")                 # projects/.../processors/XXXX
DOC_PRC_LOC  = os.getenv("DOC_PRC_LOC", "eu")            # client endpoint 用
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET")               # gs:// は付けずバケット名だけ

app = FastAPI()
_gcs = storage.Client()
_docai_client = None

def _docai():
    global _docai_client
    if _docai_client is None:
        endpoint = f"{DOC_PRC_LOC}-documentai.googleapis.com"
        _docai_client = documentai.DocumentProcessorServiceClient(
            client_options=ClientOptions(api_endpoint=endpoint)
        )
    return _docai_client

def _now_iso():
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat().replace("+00:00","Z")

def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

NORMALIZE_KIND = {
    "invoice_id": "invoice_number",
    "supplier": "vendor_name",
    "vendor": "vendor_name",
    "total_amount": "total_amount",
    "invoice_date": "invoice_date",
    "date": "invoice_date",
    "currency": "currency",
}

def _entity_to_ann(e) -> Dict:
    kind = NORMALIZE_KIND.get(getattr(e, "type_", None), f"other:{getattr(e,'type_',None)}")
    mention = getattr(e, "mention_text", None)
    norm = None
    try:
        # 一部のエンティティには normalized_value がある（なければNone）
        norm = getattr(e, "normalized_value", None)
        if hasattr(norm, "text"):
            norm = norm.text
    except Exception:
        pass

    conf = getattr(e, "confidence", None)

    page_num, bbox = None, None
    pa = getattr(e, "page_anchor", None)
    if pa and getattr(pa, "page_refs", None):
        pr = pa.page_refs[0]
        page_num = getattr(pr, "page", None)
        poly = getattr(pr, "bounding_poly", None)
        if poly and poly.normalized_vertices:
            xs = [v.x for v in poly.normalized_vertices]
            ys = [v.y for v in poly.normalized_vertices]
            bbox = [min(xs), min(ys), max(xs), max(ys)]

    return {
        "kind": kind,
        "value": norm or mention,
        "confidence": conf,
        "raw": { "type": getattr(e, "type_", None), "mention": mention, "normalized": norm },
        "loc": { "page": page_num, "bbox": bbox } if page_num is not None and bbox else None
    }

@app.get("/")
def root():
    return {"ok": True}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/")
async def events(request: Request):
    ce_type = request.headers.get("ce-type")
    ce_id   = request.headers.get("ce-id")
    ce_src  = request.headers.get("ce-source")

    try:
        body = await request.json()
    except Exception as e:
        log.error(json.dumps({"phase":"parse-error","err":str(e)}))
        return Response(status_code=204)

    bucket = body.get("bucket")
    name   = body.get("name")
    ctype  = body.get("contentType") or mimetypes.guess_type(name or "")[0] or "application/octet-stream"

    log.info(json.dumps({
        "phase":"event-received","ce_type":ce_type,"ce_id":ce_id,"ce_source":ce_src,
        "bucket":bucket,"name":name,"contentType":ctype
    }))

    # PDF 以外はスキップ
    if ctype != "application/pdf":
        log.info(json.dumps({"phase":"skip-nonpdf","name":name,"contentType":ctype}))
        return Response(status_code=204)

    # ダウンロード
    try:
        blob = _gcs.bucket(bucket).blob(name)
        content = blob.download_as_bytes()
    except Exception as e:
        log.error(json.dumps({"phase":"gcs-download-error","bucket":bucket,"name":name,"err":str(e)}))
        return Response(status_code=204)

    # DocAI
    if not DOC_PRC_NAME:
        log.error(json.dumps({"phase":"docai-misconfig","err":"DOC_PRC_NAME not set"}))
        return Response(status_code=204)

    try:
        request_doc = {
            "name": DOC_PRC_NAME,
            "raw_document": {"content": content, "mime_type": "application/pdf"},
        }
        result = _docai().process_document(request=request_doc)
        doc = result.document
        num_pages = len(doc.pages)
        text_len  = len(doc.text or "")
        langs = []
        try:
            # ページ毎のdetected_languages から上位を抽出
            seen = {}
            for p in doc.pages:
                for dl in getattr(p, "detected_languages", []):
                    seen[dl.language_code] = max(seen.get(dl.language_code, 0.0), dl.confidence)
            langs = sorted(seen, key=seen.get, reverse=True)[:3]
        except Exception:
            pass

        # アノテーション正規化
        annotations = []
        for e in (getattr(doc, "entities", []) or []):
            try:
                annotations.append(_entity_to_ann(e))
            except Exception as ex:
                log.error(json.dumps({"phase":"entity-normalize-error","err":str(ex)}))

        # 派生値（derived）：よく使うキーだけ拾っておく（ない場合は省略）
        def pick_first(k):
            hits = [a for a in annotations if a["kind"] == k and a.get("value") is not None]
            return hits[0] if hits else None

        derived = {}
        for k in ["invoice_number","vendor_name","total_amount","invoice_date","currency"]:
            hit = pick_first(k)
            if hit:
                v = hit["value"]
                # 数値化（total_amount）
                if k == "total_amount":
                    try:
                        v = float(str(v).replace(",",""))
                    except Exception:
                        pass
                derived[k] = {"value": v, "confidence": hit.get("confidence")}

        # 出力キーをv1パスへ
        out_key = f"docai-json/v1/{name}.json"

        out = {
            "schema": SCHEMA,
            "created_at": _now_iso(),
            "source": {
                "bucket": bucket, "name": name, "generation": blob.generation,
                "size": blob.size, "content_type": ctype, "sha256": _sha256(content)
            },
            "event": {"ce_type": ce_type, "ce_id": ce_id, "ce_source": ce_src},
            "processor": {"name": DOC_PRC_NAME, "location": DOC_PRC_LOC, "version": "unknown"},
            "document": {"pages": num_pages, "text_len": text_len, "languages": langs},
            "annotations": annotations,
            "derived": derived,
            "output": {"bucket": OUTPUT_BUCKET, "key": out_key},
            "errors": []
        }

        if not OUTPUT_BUCKET:
            log.error(json.dumps({"phase":"write-output","err":"OUTPUT_BUCKET not set"}))
            return Response(status_code=204)

        _gcs.bucket(OUTPUT_BUCKET).blob(out_key).upload_from_string(
            json.dumps(out, ensure_ascii=False), content_type="application/json"
        )
        log.info(json.dumps({"phase":"write-output","ok":True,"url":f"gs://{OUTPUT_BUCKET}/{out_key}"}))

    except Exception as e:
        log.error(json.dumps({"phase":"docai-error","err":str(e)}))

    return Response(status_code=204)