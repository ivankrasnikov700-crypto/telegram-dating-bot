# api/server.py
# FastAPI web server — Mini App backend + photo proxy

import hmac
import hashlib
import json
import os
import time
import urllib.parse

import requests as req_lib
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import BOT_TOKEN
from database import register_user, get_usd_balance, get_user, get_connection, _cur
from database.models import get_all_models, get_model, get_all_media, get_model_by_telegram_id
from database.chat_sessions import (
    activate_day_chat,
    get_active_chat,
    get_fan_active_chats,
    get_model_active_chats,
    InsufficientBalanceError,
    ActiveChatExistsError,
)

app = FastAPI(docs_url=None, redoc_url=None)

MINI_APP_DEV = os.environ.get("MINI_APP_DEV", "0") == "1"
if MINI_APP_DEV:
    print("[API] ⚠️  MINI_APP_DEV mode enabled — auth validation skipped!")


# ─────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────

def _validate_init_data(init_data: str) -> dict | None:
    """Validate Telegram WebApp initData via HMAC-SHA256."""
    if MINI_APP_DEV:
        return {"id": 999999, "first_name": "DevUser", "username": "devuser"}
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
    if MINI_APP_DEV:
        return {"id": 999999, "first_name": "DevUser", "username": "devuser"}
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
    db_user = get_user(uid)
    balance = get_usd_balance(uid)
    chats = get_fan_active_chats(uid)
    return {
        "user_id": uid,
        "balance_usd": round(float(balance), 2),
        "active_chats": len(chats),
        "user_role": db_user.get("user_role", "fan") if db_user else "fan",
    }


@app.get("/api/model/dashboard")
def model_dashboard(authorization: str = Header(None)):
    user = _auth(authorization)
    uid = int(user["id"])
    db_user = get_user(uid)
    if not db_user or db_user.get("user_role") != "model":
        raise HTTPException(status_code=403, detail="Not a model")

    model_profile = get_model_by_telegram_id(uid)
    chats = get_model_active_chats(uid)
    now = int(time.time())

    chats_data = []
    for chat in chats:
        fan_id = chat["fan_id"]
        fan = get_user(fan_id)
        if fan and fan.get("username"):
            fan_name = "@" + fan["username"]
        elif fan and fan.get("full_name") and fan["full_name"].strip():
            fan_name = fan["full_name"]
        else:
            fan_name = "Фанат #" + str(fan_id)
        remaining = max(0, int(chat["expires_at"]) - now)
        chats_data.append({
            "fan_id":       fan_id,
            "fan_name":     fan_name,
            "hours_left":   remaining // 3600,
            "minutes_left": (remaining % 3600) // 60,
        })

    since = now - 30 * 86400
    conn = get_connection()
    cursor = _cur(conn)
    try:
        cursor.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) AS total FROM balance_transactions "
            "WHERE user_id = %s AND amount_usd > 0 AND created_at >= %s",
            (uid, since),
        )
        monthly = round(float(cursor.fetchone()["total"]), 2)
    finally:
        conn.close()

    return {
        "name": model_profile["name"] if model_profile else (db_user.get("full_name") or "Модель"),
        "balance_usd": round(float(get_usd_balance(uid)), 2),
        "monthly_earnings": monthly,
        "active_chats": chats_data,
        "profile": {
            "preview_photo": model_profile["preview_photo"] if model_profile else None,
            "age":           model_profile.get("age") if model_profile else None,
            "description":   model_profile.get("description", "") if model_profile else "",
        } if model_profile else None,
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
    tg_uid = m.get("telegram_user_id")
    active = get_active_chat(fan_id, tg_uid) if tg_uid else None
    hours_left = 0
    if active:
        hours_left = max(0, (int(active["expires_at"]) - int(time.time())) // 3600)
    photos = [x["file_id"] for x in media if x.get("media_type") == "photo"]
    return {
        "id":              m["id"],
        "name":            m["name"],
        "age":             m.get("age"),
        "description":     m.get("description") or "",
        "preview_photo":   m.get("preview_photo"),
        "photos":          photos,
        "available":       bool(tg_uid),
        "has_active_chat": bool(active),
        "hours_left":      hours_left,
    }


@app.post("/api/chats/start")
async def start_chat(request: Request, authorization: str = Header(None)):
    user = _auth(authorization)
    body = await request.json()
    model_id = body.get("model_id")
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id required")
    m = get_model(int(model_id))
    tg_uid = m.get("telegram_user_id") if m else None
    if not tg_uid:
        raise HTTPException(status_code=503, detail="Model not available yet")
    try:
        result = activate_day_chat(int(user["id"]), tg_uid)
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
