def register_callback_handlers(bot):
    
    @bot.callback_query_handler(func=lambda call: True)
    def callback_handler(call):
        if call.data == "hello":
            bot.answer_callback_query(call.id, "Привет! 😊")
            bot.send_message(call.message.chat.id, "Рады тебя видеть в нашем клубе ❤️")
