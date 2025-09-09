# app.py（抜粋。既存の構成に差し替えでOK）
import os, json, logging, sys
from fastapi import FastAPI, Request, Response
# 必要なら解除： from google.cloud import storage

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("fac")

app = FastAPI()

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
    except Exception:
        log.exception("failed to parse JSON body")
        return Response(status_code=204)  # Eventarc は 2xx 即返し推奨

    bucket = body.get("bucket")
    name   = body.get("name")
    size   = body.get("size")
    ctype  = body.get("contentType")

    # 構造化ログ（Logs Explorer で拾いやすい）
    log.info(json.dumps({
        "phase": "event-received",
        "ce_type": ce_type, "ce_id": ce_id, "ce_source": ce_src,
        "bucket": bucket, "name": name, "size": size, "contentType": ctype
    }))

    # もし GCS 本体を読むなら（権限: Storage Object Viewer が実行SAに必要）
    # client = storage.Client()
    # blob = client.bucket(bucket).blob(name)
    # data = blob.download_as_bytes()
    # TODO: DocAI / 解析処理へ

    return Response(status_code=204)