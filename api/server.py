# api/server.py
# FastAPI web server — Mini App backend + photo proxy

import hmac
import hashlib
import json
import time
import urllib.parse

import requests as req_lib
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import BOT_TOKEN
from database import register_user, get_usd_balance
from database.models import get_all_models, get_model, get_all_media
from database.chat_sessions import (
    activate_day_chat,
    get_active_chat,
    get_fan_active_chats,
    InsufficientBalanceError,
    ActiveChatExistsError,
)

app = FastAPI(docs_url=None, redoc_url=None)


# ─────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────

def _validate_init_data(init_data: str) -> dict | None:
    """Validate Telegram WebApp initData via HMAC-SHA256."""
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        hash_val = parsed.pop("hash", "")
        check_str = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, hash_val):
            return None
        return json.loads(parsed.get("user", "{}"))
    except Exception:
        return None


def _auth(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("tma "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = _validate_init_data(authorization[4:])
    if not user:
        raise HTTPException(status_code=401, detail="Invalid initData")
    return user


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@app.get("/api/me")
def get_me(authorization: str = Header(None)):
    user = _auth(authorization)
    uid = int(user["id"])
    register_user(uid, user.get("username", ""), user.get("first_name", ""))
    balance = get_usd_balance(uid)
    chats = get_fan_active_chats(uid)
    return {
        "user_id": uid,
        "balance_usd": round(float(balance), 2),
        "active_chats": len(chats),
    }


@app.get("/api/models")
def list_models(authorization: str = Header(None)):
    _auth(authorization)
    models = get_all_models()
    return [
        {
            "id":            m["id"],
            "name":          m["name"],
            "age":           m.get("age"),
            "description":   m.get("description") or "",
            "preview_photo": m.get("preview_photo"),
        }
        for m in models
    ]


@app.get("/api/models/{model_id}")
def get_model_detail(model_id: int, authorization: str = Header(None)):
    user = _auth(authorization)
    m = get_model(model_id)
    if not m:
        raise HTTPException(status_code=404, detail="Not found")
    media = get_all_media(model_id)
    fan_id = int(user["id"])
    active = get_active_chat(fan_id, model_id)
    hours_left = 0
    if active:
        hours_left = max(0, (int(active["expires_at"]) - int(time.time())) // 3600)
    photos = [x["file_id"] for x in media if x.get("media_type") == "photo"]
    return {
        "id":             m["id"],
        "name":           m["name"],
        "age":            m.get("age"),
        "description":    m.get("description") or "",
        "preview_photo":  m.get("preview_photo"),
        "photos":         photos,
        "has_active_chat": bool(active),
        "hours_left":     hours_left,
    }


@app.post("/api/chats/start")
async def start_chat(request: Request, authorization: str = Header(None)):
    user = _auth(authorization)
    body = await request.json()
    model_id = body.get("model_id")
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id required")
    try:
        result = activate_day_chat(int(user["id"]), int(model_id))
        return {"ok": True, "expires_at": result["expires_at"]}
    except InsufficientBalanceError:
        raise HTTPException(status_code=402, detail="Insufficient balance")
    except ActiveChatExistsError:
        raise HTTPException(status_code=409, detail="Chat already active")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/photo/{file_id:path}")
def proxy_photo(file_id: str):
    """Proxy Telegram photos — hides BOT_TOKEN from frontend."""
    try:
        r = req_lib.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=8,
        )
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        img = req_lib.get(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}",
            timeout=15,
            stream=True,
        )
        img.raise_for_status()
        content_type = img.headers.get("Content-Type", "image/jpeg")
        return StreamingResponse(img.iter_content(chunk_size=8192), media_type=content_type)
    except Exception as e:
        print("[PHOTO PROXY] " + str(e))
        raise HTTPException(status_code=404, detail="Photo not found")


# Static files — must be mounted LAST (catches everything not matched above)
app.mount("/", StaticFiles(directory="miniapp", html=True), name="miniapp")
