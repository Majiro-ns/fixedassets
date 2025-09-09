from fastapi import FastAPI, Request, Response

app = FastAPI()


@app.get("/")  # ← 追加：/ も 200 にする
def root():
    return {"ok": True}


@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/__routes")
def routes():
    return {"routes": [r.path for r in app.router.routes]}

# Eventarc(GCS) からの CloudEvent を受ける受け口
# Eventarcはデフォルトで "/" に POST（Binary CloudEvents形式）
# @app.post("/")
# async def events(request: Request):
#     # 重要ヘッダ（ログ確認用）
#     ce_type = request.headers.get("ce-type")
#     ce_id   = request.headers.get("ce-id")
#     ce_src  = request.headers.get("ce-source")
#     body = await request.json()
#     # TODO: ここで body["bucket"], body["name"] などを処理
#     print({"ce_type": ce_type, "ce_id": ce_id, "ce_source": ce_src, "body_keys": list(body.keys())})
#     # 204でOK（高速応答でリトライを防ぐ）
#     return Response(status_code=204)