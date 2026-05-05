import time
import threading
from telebot import types
from keyboards.inline import (
    get_main_menu, 
    get_subscription_menu, 
    get_payment_keyboard,
    get_confirmation_menu
)
from utils.payments import generate_payment_invoice, format_payment_message
from utils.blockchain import check_payment
import asyncio

# Хранилище активных платежей
active_payments = {}

def register_callback_handlers(bot):
    
    @bot.callback_query_handler(func=lambda call: call.data == "subscription")
    def subscription_menu(call):
        """Показывает меню подписок"""
        markup = get_subscription_menu()
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="🎯 Выбери подписку:",
            reply_markup=markup
        )
    
    @bot.callback_query_handler(func=lambda call: call.data == "sub_free")
    def free_subscription(call):
        """Обработка бесплатной подписки"""
        bot.answer_callback_query(call.id, "🎉 Обычная подписка активирована!", show_alert=True)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ Обычная подписка активирована!\n\n"
                 "Ты получил доступ к:\n"
                 "• Просмотр профилей\n"
                 "• Ограниченное количество лайков\n\n"
                 "Хочешь премиум? Обновись в любой момент!",
            reply_markup=get_main_menu()
        )
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("sub_premium_"))
    def premium_subscription(call):
        """Обработка премиум подписки и генерация платежа"""
        sub_type = call.data.replace("sub_", "")
        user_id = call.from_user.id
        
        # Генерируем счёт на оплату
        invoice = generate_payment_invoice(sub_type, user_id)
        
        # Сохраняем активный платёж
        active_payments[user_id] = invoice
        
        # Форматируем сообщение с деталями платежа
        payment_text = format_payment_message(invoice)
        
        # Получаем клавиатуру с кнопками оплаты
        markup = get_payment_keyboard(invoice['amount_ltc'], invoice['wallet'])
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=payment_text,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        
        print(f"[PAYMENT] User {user_id} - Type: {sub_type} - Amount: {invoice['amount_ltc']} LTC")
        
        # Запускаем проверку платежа в отдельном потоке
        thread = threading.Thread(
            target=monitor_payment,
            args=(bot, call.message.chat.id, user_id, invoice)
        )
        thread.daemon = True
        thread.start()
    
    @bot.callback_query_handler(func=lambda call: call.data == "copy_wallet")
    def copy_wallet(call):
        """Кнопка копирования адреса кошелька"""
        user_id = call.from_user.id
        if user_id in active_payments:
            wallet = active_payments[user_id]['wallet']
            bot.answer_callback_query(
                call.id, 
                f"📋 Адрес скопирован:\n{wallet}", 
                show_alert=True
            )
        else:
            bot.answer_callback_query(call.id, "❌ Платёж не найден", show_alert=True)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("copy_amount_"))
    def copy_amount(call):
        """Кнопка копирования суммы в LTC"""
        amount = call.data.replace("copy_amount_", "")
        bot.answer_callback_query(
            call.id, 
            f"💰 Сумма скопирована:\n{amount} LTC", 
            show_alert=True
        )
    
    @bot.callback_query_handler(func=lambda call: call.data == "payment_confirmed")
    def payment_confirmed(call):
        """Обработка подтверждения платежа"""
        bot.answer_callback_query(call.id, "✅ Спасибо за оплату!", show_alert=True)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ Премиум подписка активирована!\n\n"
                 "Теперь ты имеешь доступ к:\n"
                 "• ⭐ Неограниченное количество лайков\n"
                 "• 👁 Просмотр онлайна других пользователей\n"
                 "• 🎯 Приоритетный показ твоего профиля\n"
                 "• 🚫 Удаление рекламы\n"
                 "• 💎 Премиум значок на профиле\n\n"
                 "Спасибо за доверие! ❤️",
            reply_markup=get_main_menu()
        )
    
    @bot.callback_query_handler(func=lambda call: call.data == "back_to_menu")
    def back_to_main(call):
        """Возврат в главное меню"""
        markup = get_main_menu()
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❤️ Главное меню",
            reply_markup=markup
        )
    
    @bot.callback_query_handler(func=lambda call: call.data == "hello")
    def hello_handler(call):
        """Приветствие"""
        bot.answer_callback_query(call.id, "👋 Привет!", show_alert=True)
        bot.send_message(call.message.chat.id, "Рады тебя видеть в нашем клубе ❤️")
    
    @bot.callback_query_handler(func=lambda call: call.data == "girls")
    def girls_handler(call):
        """Каталог девушек"""
        bot.answer_callback_query(call.id, "👭 Каталог (в разработке)", show_alert=True)


def monitor_payment(bot, chat_id, user_id, invoice):
    """Отслеживает платёж в отдельном потоке"""
    import time
    from config import LTC_WALLET
    
    wallet = LTC_WALLET
    expected_amount = invoice['amount_ltc']
    timeout = 3600  # 60 минут
    check_interval = 30  # Проверяем каждые 30 секунд
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            # Проверяем платёж
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            payment_received, amount = loop.run_until_complete(
                check_payment(wallet, expected_amount, timeout=1)
            )
            loop.close()
            
            if payment_received:
                print(f"[SUCCESS] Payment received from user {user_id}: {amount} LTC")
                
                # Отправляем сообщение об активации
                bot.send_message(
                    chat_id,
                    "✅ **ПЛАТЁЖ ПОЛУЧЕН!**\n\n"
                    f"💰 Получено: {amount} LTC\n"
                    "🎉 Премиум подписка активирована!\n\n"
                    "Спасибо за поддержку! ❤️",
                    parse_mode="Markdown"
                )
                
                # Удаляем из активных платежей
                if user_id in active_payments:
                    del active_payments[user_id]
                
                return
            
            time.sleep(check_interval)
        
        except Exception as e:
            print(f"[ERROR] Payment monitoring failed: {e}")
            time.sleep(check_interval)
    
    # Если время истекло
    print(f"[TIMEOUT] Payment not received from user {user_id}")
    bot.send_message(
        chat_id,
        "⏰ **ВРЕМЯ ИСТЕКЛО**\n\n"
        "Счёт на оплату более не действителен.\n"
        "Создайте новый счёт в меню подписок.",
        parse_mode="Markdown"
    )
    
    if user_id in active_payments:
        del active_payments[user_id]
