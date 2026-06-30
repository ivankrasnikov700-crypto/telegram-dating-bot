from database.paid_media import get_paid_media, unlock_and_pay


def register_paid_media_handlers(bot):

    @bot.callback_query_handler(func=lambda call: call.data.startswith("unlock_"))
    def handle_unlock(call):
        fan_id = call.from_user.id
        bot.answer_callback_query(call.id)

        try:
            media_id = int(call.data.replace("unlock_", ""))
        except ValueError:
            return

        media = get_paid_media(media_id)
        if not media or media["fan_user_id"] != fan_id:
            bot.send_message(fan_id, "❌ Медиа не найдено.")
            return

        if media["is_unlocked"]:
            _send_original(bot, fan_id, media)
            return

        ok, result = unlock_and_pay(media_id, fan_id)

        if not ok:
            if result == "insufficient":
                from keyboards.inline import get_topup_menu
                bot.send_message(
                    fan_id,
                    "❌ Недостаточно средств.\n\n"
                    "Пополни баланс и попробуй снова 👇",
                    reply_markup=get_topup_menu()
                )
            elif result == "already_unlocked":
                _send_original(bot, fan_id, media)
            else:
                bot.send_message(fan_id, "❌ Ошибка разблокировки. Попробуй позже.")
            return

        _send_original(bot, fan_id, result)
        price     = float(result["price_usd"])
        model_id  = result["model_user_id"]
        try:
            bot.send_message(
                model_id,
                "💰 Фанат разблокировал твоё фото!\n"
                "💵 Твой заработок: $" + str(round(price * 0.70, 2))
            )
        except Exception as e:
            print("[PAID MEDIA] Уведомление модели не доставлено: " + str(e))


def _send_original(bot, fan_id: int, media: dict):
    """Sends the original (unlocked) file to the fan."""
    file_id   = media["file_id"]
    file_type = media.get("file_type", "photo")
    try:
        if file_type == "video":
            bot.send_video(fan_id, file_id, caption="🔓 Эксклюзивное видео разблокировано!")
        else:
            bot.send_photo(fan_id, file_id, caption="🔓 Эксклюзивное фото разблокировано!")
    except Exception as e:
        print("[PAID MEDIA] Не удалось отправить оригинал " + str(fan_id) + ": " + str(e))
        bot.send_message(fan_id, "❌ Не удалось доставить медиа. Обратись к администратору.")
