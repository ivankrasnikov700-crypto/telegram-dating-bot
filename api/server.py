# api/server.py
# FastAPI web server — Mini App backend + photo proxy

import hmac
import hashlib
import json
import os
import time
import urllib.parse

import io
import requests as req_lib
import telebot as _telebot
from fastapi import FastAPI, HTTPException, Header, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import BOT_TOKEN, ADMIN_IDS, MINI_APP_URL
from bot_instance import bot as _webhook_bot
from database import register_user, get_usd_balance, get_user, get_connection, _cur, ban_user, unban_user, add_usd_balance
from database.models import (
    get_all_models, get_model, get_all_media, get_model_by_telegram_id,
    add_model, set_preview_photo, add_model_media,
)
from database.chat_sessions import (
    activate_day_chat,
    get_active_chat,
    get_fan_active_chats,
    get_model_active_chats,
    InsufficientBalanceError,
    ActiveChatExistsError,
)
from database.paid_media import create_paid_media, get_paid_media, unlock_and_pay
from database.withdrawals import get_pending_withdrawals, get_withdrawal, process_withdrawal
from utils.cryptobot import is_configured as _cp_configured, create_invoice, get_invoice, transfer as cp_transfer, usd_to_asset

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


def _admin_auth(authorization: str | None) -> dict:
    user = _auth(authorization)
    if int(user["id"]) not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Not admin")
    return user


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
# Chat helpers: notifications + media serialization
# ─────────────────────────────────────────────

def _notify_chat_message(target_tg_id: int, deep_link_id: int, sender_label: str, preview_text: str):
    """Sends a Telegram DM with a button that deep-links back into the chat in the Mini App."""
    text = sender_label + ":\n\n" + preview_text
    markup = None
    if MINI_APP_URL:
        try:
            url = MINI_APP_URL.rstrip("/") + "?chat=" + str(deep_link_id)
            markup = _telebot.types.InlineKeyboardMarkup()
            markup.add(_telebot.types.InlineKeyboardButton(
                "💬 Открыть чат", web_app=_telebot.types.WebAppInfo(url=url)
            ))
        except Exception:
            markup = None
    try:
        _webhook_bot.send_message(target_tg_id, text, reply_markup=markup)
    except Exception as e:
        print("[CHAT NOTIFY] Не удалось уведомить " + str(target_tg_id) + ": " + str(e))


def _media_payload(media_id: int, viewer_is_owner: bool) -> dict | None:
    """Builds the media block for a chat message: locked preview or full unlocked URL."""
    media = get_paid_media(media_id)
    if not media:
        return None
    unlocked = viewer_is_owner or bool(media.get("is_unlocked"))
    payload = {
        "media_id":  media["id"],
        "file_type": media.get("file_type", "photo"),
        "price_usd": round(float(media.get("price_usd") or 0), 2),
        "unlocked":  unlocked,
    }
    if unlocked:
        payload["url"] = "/api/photo/" + media["file_id"]
    elif media.get("preview_file_id"):
        payload["preview_url"] = "/api/photo/" + media["preview_file_id"]
    return payload


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
    role = db_user.get("user_role", "fan") if db_user else "fan"
    if role != "model" and get_model_by_telegram_id(uid):
        role = "model"
        conn = get_connection()
        conn.cursor().execute("UPDATE users SET user_role = 'model' WHERE user_id = %s", (uid,))
        conn.commit()
        conn.close()
    return {
        "user_id": uid,
        "balance_usd": round(float(balance), 2),
        "active_chats": len(chats),
        "user_role": role,
        "is_admin": uid in ADMIN_IDS,
    }


@app.get("/api/model/dashboard")
def model_dashboard(authorization: str = Header(None)):
    user = _auth(authorization)
    uid = int(user["id"])
    db_user = get_user(uid)
    model_profile = get_model_by_telegram_id(uid)
    if not model_profile:
        raise HTTPException(status_code=403, detail="Not a model")
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


# ─────────────────────────────────────────────
# Chat: Fan ↔ Model messaging
# ─────────────────────────────────────────────

@app.post("/api/chat/{model_id}/send")
async def fan_send_message(model_id: int, request: Request, authorization: str = Header(None)):
    user = _auth(authorization)
    fan_id = int(user["id"])
    body = await request.json()
    content = (body.get("text") or "").strip()[:2000]
    if not content:
        raise HTTPException(status_code=400, detail="Empty message")
    model = get_model(model_id)
    tg_uid = model.get("telegram_user_id") if model else None
    if not tg_uid:
        raise HTTPException(status_code=403, detail="Model not available")
    conn = get_connection(); cur = _cur(conn)
    try:
        cur.execute(
            "SELECT chat_id FROM model_chats WHERE fan_id=%s AND model_id=%s AND is_active=1 AND expires_at>%s",
            (fan_id, tg_uid, int(time.time()))
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=403, detail="No active chat")
        cur.execute(
            "INSERT INTO chat_messages (chat_id, sender_id, sender_role, content, created_at) VALUES (%s,%s,'fan',%s,%s)",
            (row["chat_id"], fan_id, content, int(time.time()))
        )
        conn.commit()
    finally:
        conn.close()
    _notify_chat_message(tg_uid, fan_id, "💌 Фанат", content[:300])
    return {"ok": True}


@app.get("/api/chat/{model_id}/messages")
def fan_get_messages(model_id: int, since: int = 0, authorization: str = Header(None)):
    user = _auth(authorization)
    fan_id = int(user["id"])
    model = get_model(model_id)
    tg_uid = model.get("telegram_user_id") if model else None
    if not tg_uid:
        return []
    conn = get_connection(); cur = _cur(conn)
    try:
        cur.execute(
            "SELECT chat_id FROM model_chats WHERE fan_id=%s AND model_id=%s AND is_active=1 AND expires_at>%s",
            (fan_id, tg_uid, int(time.time()))
        )
        row = cur.fetchone()
        if not row:
            return []
        cur.execute(
            "SELECT id, sender_role, content, created_at, media_id FROM chat_messages WHERE chat_id=%s AND id>%s ORDER BY created_at ASC LIMIT 100",
            (row["chat_id"], since)
        )
        msgs = cur.fetchall()
    finally:
        conn.close()
    result = []
    for m in msgs:
        item = {"id": m["id"], "role": m["sender_role"], "text": m["content"], "ts": m["created_at"]}
        if m.get("media_id"):
            item["media"] = _media_payload(m["media_id"], viewer_is_owner=False)
        result.append(item)
    return result


@app.post("/api/model/chat/{fan_id}/send")
async def model_send_message(fan_id: int, request: Request, authorization: str = Header(None)):
    user = _auth(authorization)
    model_user_id = int(user["id"])
    body = await request.json()
    content = (body.get("text") or "").strip()[:2000]
    if not content:
        raise HTTPException(status_code=400, detail="Empty message")
    conn = get_connection(); cur = _cur(conn)
    try:
        cur.execute(
            "SELECT chat_id FROM model_chats WHERE fan_id=%s AND model_id=%s AND is_active=1 AND expires_at>%s",
            (fan_id, model_user_id, int(time.time()))
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=403, detail="No active chat")
        cur.execute(
            "INSERT INTO chat_messages (chat_id, sender_id, sender_role, content, created_at) VALUES (%s,%s,'model',%s,%s)",
            (row["chat_id"], model_user_id, content, int(time.time()))
        )
        conn.commit()
    finally:
        conn.close()
    model_profile = get_model_by_telegram_id(model_user_id)
    model_catalog_id = model_profile["id"] if model_profile else model_user_id
    model_name = model_profile["name"] if model_profile else "Модель"
    _notify_chat_message(fan_id, model_catalog_id, "💌 " + model_name, content[:300])
    return {"ok": True}


@app.get("/api/model/chat/{fan_id}/messages")
def model_get_messages(fan_id: int, since: int = 0, authorization: str = Header(None)):
    user = _auth(authorization)
    model_user_id = int(user["id"])
    conn = get_connection(); cur = _cur(conn)
    try:
        cur.execute(
            "SELECT chat_id FROM model_chats WHERE fan_id=%s AND model_id=%s AND is_active=1 AND expires_at>%s",
            (fan_id, model_user_id, int(time.time()))
        )
        row = cur.fetchone()
        if not row:
            return []
        cur.execute(
            "SELECT id, sender_role, content, created_at, media_id FROM chat_messages WHERE chat_id=%s AND id>%s ORDER BY created_at ASC LIMIT 100",
            (row["chat_id"], since)
        )
        msgs = cur.fetchall()
    finally:
        conn.close()
    result = []
    for m in msgs:
        item = {"id": m["id"], "role": m["sender_role"], "text": m["content"], "ts": m["created_at"]}
        if m.get("media_id"):
            item["media"] = _media_payload(m["media_id"], viewer_is_owner=True)
        result.append(item)
    return result


@app.post("/api/model/chat/{fan_id}/send_media")
async def model_send_media(
    fan_id: int,
    authorization: str = Header(None),
    file: UploadFile = File(...),
    price: float = Form(0),
):
    """Model attaches a photo/video to the chat. If price > 0, it's blurred until the fan pays."""
    user = _auth(authorization)
    model_user_id = int(user["id"])
    model_profile = get_model_by_telegram_id(model_user_id)
    if not model_profile:
        raise HTTPException(status_code=403, detail="Not a model")

    conn = get_connection(); cur = _cur(conn)
    try:
        cur.execute(
            "SELECT chat_id FROM model_chats WHERE fan_id=%s AND model_id=%s AND is_active=1 AND expires_at>%s",
            (fan_id, model_user_id, int(time.time()))
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=403, detail="No active chat")
        chat_id = row["chat_id"]
    finally:
        conn.close()

    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")
    content_type = (file.content_type or "").lower()
    file_type = "video" if content_type.startswith("video") else "photo"
    price = max(0.0, round(float(price), 2))

    try:
        tbot = _telebot.TeleBot(BOT_TOKEN)
        admin_id = ADMIN_IDS[0]
        if file_type == "video":
            msg = tbot.send_video(admin_id, io.BytesIO(data))
            full_file_id = msg.video.file_id
        else:
            msg = tbot.send_photo(admin_id, io.BytesIO(data))
            full_file_id = msg.photo[-1].file_id
        try:
            tbot.delete_message(admin_id, msg.message_id)
        except Exception:
            pass

        preview_file_id = None
        if price > 0 and file_type == "photo":
            try:
                from PIL import Image, ImageFilter
                img = Image.open(io.BytesIO(data)).convert("RGB")
                blurred = img.filter(ImageFilter.GaussianBlur(radius=20))
                buf = io.BytesIO()
                blurred.save(buf, format="JPEG", quality=70)
                buf.seek(0)
                pmsg = tbot.send_photo(admin_id, buf)
                preview_file_id = pmsg.photo[-1].file_id
                try:
                    tbot.delete_message(admin_id, pmsg.message_id)
                except Exception:
                    pass
            except Exception as e:
                print("[CHAT MEDIA] Blur error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Upload failed: " + str(e))

    media_id = create_paid_media(model_user_id, fan_id, full_file_id, file_type, price, preview_file_id)
    if price <= 0:
        conn = get_connection()
        conn.cursor().execute("UPDATE paid_media SET is_unlocked = 1 WHERE id = %s", (media_id,))
        conn.commit(); conn.close()

    conn = get_connection(); cur2 = conn.cursor()
    cur2.execute(
        "INSERT INTO chat_messages (chat_id, sender_id, sender_role, content, created_at, media_id) "
        "VALUES (%s,%s,'model',%s,%s,%s)",
        (chat_id, model_user_id, "", int(time.time()), media_id)
    )
    conn.commit(); conn.close()

    label = "🔒 Платное " + ("видео" if file_type == "video" else "фото") if price > 0 else \
            ("🎬 Видео" if file_type == "video" else "📸 Фото")
    _notify_chat_message(fan_id, model_profile["id"], "💌 " + model_profile.get("name", "Модель"), label)

    return {"ok": True, "media_id": media_id}


@app.post("/api/chat/media/{media_id}/unlock")
def fan_unlock_media(media_id: int, authorization: str = Header(None)):
    user = _auth(authorization)
    fan_id = int(user["id"])
    media = get_paid_media(media_id)
    if not media or media["fan_user_id"] != fan_id:
        raise HTTPException(status_code=404, detail="Not found")
    if media["is_unlocked"]:
        return {"ok": True, "url": "/api/photo/" + media["file_id"]}

    ok, result = unlock_and_pay(media_id, fan_id)
    if not ok:
        if result == "insufficient":
            raise HTTPException(status_code=402, detail="Insufficient balance")
        if result == "already_unlocked":
            media = get_paid_media(media_id)
            return {"ok": True, "url": "/api/photo/" + media["file_id"]}
        raise HTTPException(status_code=500, detail="Unlock failed")

    try:
        price = float(result["price_usd"])
        model_id = result["model_user_id"]
        _webhook_bot.send_message(
            model_id,
            "💰 Фанат разблокировал твоё медиа в чате!\n💵 Твой заработок: $" + str(round(price * 0.70, 2))
        )
    except Exception as e:
        print("[CHAT MEDIA] Не удалось уведомить модель: " + str(e))

    return {"ok": True, "url": "/api/photo/" + result["file_id"]}


@app.get("/api/me/chats")
def fan_chats_list(authorization: str = Header(None)):
    user = _auth(authorization)
    fan_id = int(user["id"])
    chats = get_fan_active_chats(fan_id)
    now = int(time.time())
    result = []
    for c in chats:
        model = get_model_by_telegram_id(c["model_id"])
        if not model:
            continue
        remaining = max(0, int(c["expires_at"]) - now)
        result.append({
            "model_id":      model["id"],
            "name":          model.get("name", "Модель"),
            "preview_photo": model.get("preview_photo"),
            "hours_left":    remaining // 3600,
            "minutes_left":  (remaining % 3600) // 60,
        })
    return result


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


# ─────────────────────────────────────────────
# Admin API
# ─────────────────────────────────────────────

@app.get("/api/admin/stats")
def admin_stats(authorization: str = Header(None)):
    _admin_auth(authorization)
    conn = get_connection()
    cursor = _cur(conn)
    now = int(time.time())
    since_30d = now - 30 * 86400
    try:
        cursor.execute("SELECT COUNT(*) AS cnt FROM users")
        total_users = int(cursor.fetchone()["cnt"])

        cursor.execute("SELECT COUNT(*) AS cnt FROM models WHERE is_active = 1")
        total_models = int(cursor.fetchone()["cnt"])

        # Tables that may be absent in older deployments — fall back to 0
        try:
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM model_chats WHERE is_active = 1 AND expires_at > %s",
                (now,),
            )
            active_chats = int(cursor.fetchone()["cnt"])
        except Exception:
            conn.rollback()
            active_chats = 0

        try:
            cursor.execute("SELECT COUNT(*) AS cnt FROM model_withdrawals WHERE status = 'pending'")
            pending_withdrawals = int(cursor.fetchone()["cnt"])
        except Exception:
            conn.rollback()
            pending_withdrawals = 0

        try:
            cursor.execute(
                """
                SELECT COALESCE(SUM(ABS(bt.amount_usd)), 0) AS total
                FROM balance_transactions bt
                JOIN users u ON u.user_id = bt.user_id
                WHERE bt.amount_usd < 0 AND u.user_role = 'fan' AND bt.created_at >= %s
                """,
                (since_30d,),
            )
            fan_spend_30d = float(cursor.fetchone()["total"])

            cursor.execute(
                """
                SELECT COALESCE(SUM(ABS(bt.amount_usd)), 0) AS total
                FROM balance_transactions bt
                JOIN users u ON u.user_id = bt.user_id
                WHERE bt.amount_usd < 0 AND u.user_role = 'fan'
                """
            )
            fan_spend_total = float(cursor.fetchone()["total"])
        except Exception:
            conn.rollback()
            fan_spend_30d = 0.0
            fan_spend_total = 0.0

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    return {
        "total_users":            total_users,
        "total_models":           total_models,
        "active_chats":           active_chats,
        "pending_withdrawals":    pending_withdrawals,
        "platform_revenue_30d":   round(fan_spend_30d * 0.30, 2),
        "platform_revenue_total": round(fan_spend_total * 0.30, 2),
    }


@app.get("/api/admin/models")
def admin_models_list(authorization: str = Header(None)):
    _admin_auth(authorization)
    conn = get_connection()
    cursor = _cur(conn)
    now = int(time.time())
    result = []
    try:
        cursor.execute(
            "SELECT id, name, age, preview_photo, telegram_user_id "
            "FROM models WHERE is_active = 1 ORDER BY created_at DESC"
        )
        model_rows = [dict(r) for r in cursor.fetchall()]

        for m in model_rows:
            tg_uid = m.get("telegram_user_id")
            active_chats   = 0
            total_earnings = 0.0
            balance_usd    = 0.0

            if tg_uid:
                try:
                    cursor.execute(
                        "SELECT COUNT(*) AS cnt FROM model_chats "
                        "WHERE model_id = %s AND is_active = 1 AND expires_at > %s",
                        (tg_uid, now),
                    )
                    active_chats = int(cursor.fetchone()["cnt"])
                except Exception:
                    conn.rollback()

                try:
                    cursor.execute(
                        "SELECT COALESCE(SUM(amount_usd), 0) AS total "
                        "FROM balance_transactions WHERE user_id = %s AND amount_usd > 0",
                        (tg_uid,),
                    )
                    total_earnings = float(cursor.fetchone()["total"])
                except Exception:
                    conn.rollback()

                try:
                    cursor.execute(
                        "SELECT balance_usd FROM users WHERE user_id = %s", (tg_uid,)
                    )
                    row = cursor.fetchone()
                    balance_usd = float(row["balance_usd"]) if row else 0.0
                except Exception:
                    conn.rollback()

            result.append({
                "id":               m["id"],
                "name":             m["name"],
                "age":              m.get("age"),
                "preview_photo":    m.get("preview_photo"),
                "telegram_user_id": tg_uid,
                "is_linked":        bool(tg_uid),
                "active_chats":     active_chats,
                "balance_usd":      round(balance_usd, 2),
                "total_earnings":   round(total_earnings, 2),
            })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    return result


@app.get("/api/admin/withdrawals")
def admin_withdrawals(authorization: str = Header(None)):
    _admin_auth(authorization)
    rows = get_pending_withdrawals()
    return [
        {
            "id":             r["id"],
            "model_user_id":  r["model_user_id"],
            "amount_usd":     round(float(r["amount_usd"]), 2),
            "ltc_address":    r["ltc_address"],
            "status":         r["status"],
            "created_at":     r.get("created_at"),
            "username":       r.get("username"),
            "full_name":      r.get("full_name"),
        }
        for r in rows
    ]


@app.post("/api/admin/withdrawals/{wid}/approve")
def admin_approve_withdrawal(wid: int, authorization: str = Header(None)):
    _admin_auth(authorization)
    w = get_withdrawal(wid)
    if not w:
        raise HTTPException(status_code=404, detail="Not found")
    if w["status"] != "pending":
        raise HTTPException(status_code=409, detail="Already processed: " + w["status"])

    notes = "Approved via Mini App admin"
    # CryptoBot auto-transfer if no LTC address
    if not w.get("ltc_address") and _cp_configured():
        asset = w.get("asset") or "USDT"
        try:
            crypto_amount = usd_to_asset(float(w["amount_usd"]), asset)
            cp_transfer(
                user_id=int(w["model_user_id"]),
                asset=asset,
                amount=crypto_amount,
                spend_id="withdrawal_" + str(wid),
                comment="Withdrawal #" + str(wid) + " — Miss Moldova",
            )
            notes = "Auto CryptoBot transfer: " + str(crypto_amount) + " " + asset
        except Exception as e:
            raise HTTPException(status_code=502, detail="CryptoBot transfer failed: " + str(e))

    result = process_withdrawal(wid, "paid", notes)
    if not result:
        raise HTTPException(status_code=500, detail="Processing failed")
    return {"ok": True}


@app.post("/api/admin/withdrawals/{wid}/reject")
async def admin_reject_withdrawal(wid: int, request: Request, authorization: str = Header(None)):
    _admin_auth(authorization)
    body = await request.json()
    reason = (body.get("reason") or "").strip() or "Отклонено администратором"
    w = get_withdrawal(wid)
    if not w:
        raise HTTPException(status_code=404, detail="Not found")
    if w["status"] != "pending":
        raise HTTPException(status_code=409, detail="Already processed: " + w["status"])
    process_withdrawal(wid, "rejected", reason)
    return {"ok": True}


@app.get("/api/admin/users")
def admin_users(authorization: str = Header(None)):
    _admin_auth(authorization)
    conn = get_connection()
    cursor = _cur(conn)
    try:
        cursor.execute(
            """
            SELECT user_id, username, full_name, balance_usd, user_role, is_banned
            FROM users
            ORDER BY user_id DESC
            LIMIT 50
            """
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [
        {
            "user_id":    r["user_id"],
            "username":   r.get("username"),
            "full_name":  r.get("full_name"),
            "balance_usd": round(float(r.get("balance_usd") or 0), 2),
            "user_role":  r.get("user_role", "fan"),
            "is_banned":  bool(r.get("is_banned")),
        }
        for r in rows
    ]


@app.post("/api/admin/users/{uid}/ban")
def admin_ban_user(uid: int, authorization: str = Header(None)):
    _admin_auth(authorization)
    if not get_user(uid):
        raise HTTPException(status_code=404, detail="User not found")
    ban_user(uid)
    return {"ok": True}


@app.post("/api/admin/users/{uid}/unban")
def admin_unban_user(uid: int, authorization: str = Header(None)):
    _admin_auth(authorization)
    if not get_user(uid):
        raise HTTPException(status_code=404, detail="User not found")
    unban_user(uid)
    return {"ok": True}


@app.post("/api/admin/users/{uid}/add_balance")
async def admin_add_balance(uid: int, request: Request, authorization: str = Header(None)):
    _admin_auth(authorization)
    body = await request.json()
    amount = float(body.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    if not get_user(uid):
        raise HTTPException(status_code=404, detail="User not found")
    add_usd_balance(uid, amount, "Пополнение администратором")
    return {"ok": True, "new_balance": round(get_usd_balance(uid), 2)}


# ─────────────────────────────────────────────
# Admin: Model Management
# ─────────────────────────────────────────────

@app.post("/api/admin/models")
async def admin_create_model(request: Request, authorization: str = Header(None)):
    _admin_auth(authorization)
    body = await request.json()
    name = (body.get("name") or "").strip()
    age  = body.get("age") or "0"
    desc = (body.get("description") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    try:
        model_id = add_model(name, str(age), "", desc)
        return {"ok": True, "model_id": model_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/models/{model_id}/upload")
async def admin_upload_model_photo(
    model_id: int,
    authorization: str = Header(None),
    file: UploadFile = File(...),
    photo_type: str = Form("preview"),
):
    _admin_auth(authorization)
    m = get_model(model_id)
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")
    try:
        bot = _telebot.TeleBot(BOT_TOKEN)
        admin_id = ADMIN_IDS[0]
        msg = bot.send_photo(admin_id, io.BytesIO(data))
        file_id = msg.photo[-1].file_id
        try:
            bot.delete_message(admin_id, msg.message_id)
        except Exception:
            pass
        if photo_type == "preview":
            set_preview_photo(model_id, file_id)
        elif photo_type == "preview2":
            from database.models import set_preview_photo_2
            set_preview_photo_2(model_id, file_id)
        else:
            is_prev = 1 if photo_type == "preview_media" else 0
            add_model_media(model_id, file_id, "photo", is_prev, 0)
        return {"ok": True, "file_id": file_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/models/{model_id}/link")
async def admin_link_model_tg(model_id: int, request: Request, authorization: str = Header(None)):
    _admin_auth(authorization)
    body = await request.json()
    tg_uid = body.get("telegram_user_id")
    if not tg_uid:
        raise HTTPException(status_code=400, detail="telegram_user_id required")
    tg_uid = int(tg_uid)
    m = get_model(model_id)
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE models SET telegram_user_id = %s WHERE id = %s", (tg_uid, model_id))
        cursor.execute(
            "INSERT INTO users (user_id, user_role, created_at) VALUES (%s, 'model', %s) "
            "ON CONFLICT (user_id) DO UPDATE SET user_role = 'model'",
            (tg_uid, int(time.time()))
        )
        conn.commit()
        return {"ok": True}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/admin/models/{model_id}/chats")
def admin_model_chats(model_id: int, authorization: str = Header(None)):
    _admin_auth(authorization)
    m = get_model(model_id)
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    tg_uid = m.get("telegram_user_id")
    if not tg_uid:
        return {"model_id": model_id, "chats": [], "linked": False}
    now   = int(time.time())
    chats = get_model_active_chats(int(tg_uid))
    result = []
    for c in chats:
        fan = get_user(c["fan_id"])
        fan_name = (
            "@" + fan["username"] if fan and fan.get("username")
            else (fan.get("full_name") or "Фанат #" + str(c["fan_id"])) if fan
            else "Фанат #" + str(c["fan_id"])
        )
        remaining = max(0, int(c["expires_at"]) - now)
        result.append({
            "fan_id":       c["fan_id"],
            "fan_name":     fan_name,
            "hours_left":   remaining // 3600,
            "minutes_left": (remaining % 3600) // 60,
            "expires_at":   c["expires_at"],
        })
    return {"model_id": model_id, "chats": result, "linked": True}


# ─────────────────────────────────────────────
# CryptoBot: Fan top-up
# ─────────────────────────────────────────────

@app.post("/api/topup/cryptobot")
async def topup_cryptobot(request: Request, authorization: str = Header(None)):
    user = _auth(authorization)
    uid  = int(user["id"])
    if not _cp_configured():
        raise HTTPException(status_code=503, detail="CryptoBot not configured")
    body   = await request.json()
    amount = float(body.get("amount_usd", 0))
    if amount not in (10, 25, 50):
        raise HTTPException(status_code=400, detail="amount_usd must be 10, 25 or 50")
    register_user(uid, user.get("username", ""), user.get("first_name", ""))
    try:
        invoice = create_invoice(
            asset="USDT",
            amount=amount,
            description="Miss Moldova balance top-up $" + str(int(amount)),
            payload=str(uid) + ":" + str(int(time.time())),
        )
        # Persist invoice for polling
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cryptobot_invoices (invoice_id, user_id, amount_usd, created_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (invoice_id) DO NOTHING",
            (invoice["invoice_id"], uid, amount, int(time.time()))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=502, detail="CryptoBot error: " + str(e))
    return {
        "ok":        True,
        "pay_url":   invoice["bot_invoice_url"],
        "invoice_id": invoice["invoice_id"],
        "amount_usd": amount,
    }


@app.get("/api/topup/cryptobot/{invoice_id}/status")
def topup_cryptobot_status(invoice_id: int, authorization: str = Header(None)):
    user = _auth(authorization)
    uid  = int(user["id"])
    if not _cp_configured():
        raise HTTPException(status_code=503, detail="CryptoBot not configured")
    try:
        inv = get_invoice(invoice_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail="CryptoBot error: " + str(e))
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    status = inv.get("status")
    if status == "paid":
        # Check if already credited
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT credited FROM cryptobot_invoices WHERE invoice_id = %s AND user_id = %s",
            (invoice_id, uid)
        )
        row = cursor.fetchone()
        if row and not row[0]:
            cursor.execute(
                "UPDATE cryptobot_invoices SET credited = TRUE WHERE invoice_id = %s",
                (invoice_id,)
            )
            conn.commit()
            conn.close()
            amount_usd = float(inv.get("amount", 0))
            add_usd_balance(uid, amount_usd, "CryptoBot top-up invoice #" + str(invoice_id))
        else:
            conn.close()

    return {"status": status, "invoice_id": invoice_id}


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


# ─────────────────────────────────────────────
# Telegram Webhook (replaces long-polling)
# ─────────────────────────────────────────────

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Receives Telegram updates when webhook mode is active."""
    try:
        data = await request.json()
        update = _telebot.types.Update.de_json(data)
        import asyncio
        # Fire-and-forget in thread pool — bot handlers are sync/blocking, must not run in event loop
        asyncio.get_event_loop().run_in_executor(
            None, _webhook_bot.process_new_updates, [update]
        )
    except Exception as e:
        print("[WEBHOOK] Error: " + str(e))
    return JSONResponse({"ok": True})


# Static files — must be mounted LAST (catches everything not matched above)
app.mount("/", StaticFiles(directory="miniapp", html=True), name="miniapp")
