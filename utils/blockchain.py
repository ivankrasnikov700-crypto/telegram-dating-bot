# utils/blockchain.py
# Модуль проверки LTC платежей через Blockchair API
#
# ПРОБЛЕМА СТАРОЙ ВЕРСИИ:
#   Сравнивался общий баланс кошелька с ожидаемой суммой.
#   Если два пользователя платили одновременно — оба получали подписку.
#   Если кошелёк уже имел баланс — платёж считался подтверждённым сразу.
#
# НОВАЯ ЛОГИКА:
#   Смотрим только транзакции которые пришли ПОСЛЕ создания инвойса.
#   Ищем транзакцию с суммой ±2% от ожидаемой.
#   Каждый платёж проверяется независимо.

import aiohttp
import asyncio
import time


async def check_payment(
    wallet: str,
    expected_amount: float,
    created_at: int = None
) -> tuple:
    """
    Проверяет поступление конкретного платежа на LTC кошелёк.

    Логика:
        1. Получаем список последних транзакций кошелька
        2. Фильтруем только те что пришли ПОСЛЕ создания инвойса
        3. Ищем транзакцию с суммой близкой к ожидаемой (±2%)

    Args:
        wallet:          LTC адрес кошелька
        expected_amount: ожидаемая сумма в LTC
        created_at:      unix timestamp создания инвойса
                         (если None — берём текущее время минус 5 минут)

    Returns:
        tuple: (найден: bool, сумма: float)
    """

    # Если время создания не передано — ищем транзакции за последние 5 минут
    if created_at is None:
        created_at = int(time.time()) - 300

    url = "https://api.blockchair.com/litecoin/dashboards/address/" + wallet

    # Параметры запроса — берём последние 10 транзакций
    params = {
        "limit": "10",        # последние 10 транзакций достаточно
        "offset": "0"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:

                if resp.status != 200:
                    print("[BLOCKCHAIN] API статус: " + str(resp.status))
                    return False, 0.0

                data = await resp.json()

                # Проверяем структуру ответа
                address_data = data.get("data", {}).get(wallet, {})
                if not address_data:
                    print("[BLOCKCHAIN] Кошелёк не найден в ответе API")
                    return False, 0.0

                # Получаем список хешей транзакций
                transactions = address_data.get("transactions", [])
                if not transactions:
                    print("[BLOCKCHAIN] Транзакций нет")
                    return False, 0.0

                print("[BLOCKCHAIN] Найдено транзакций: " + str(len(transactions)))

                # Получаем детали каждой транзакции
                for tx_hash in transactions[:5]:  # проверяем только последние 5
                    found, amount = await _check_transaction(
                        session,
                        tx_hash,
                        wallet,
                        expected_amount,
                        created_at
                    )
                    if found:
                        return True, amount

                return False, 0.0

    except asyncio.TimeoutError:
        print("[BLOCKCHAIN ERROR] Timeout при запросе к API")
        return False, 0.0

    except aiohttp.ClientError as e:
        print("[BLOCKCHAIN ERROR] Сетевая ошибка: " + str(e))
        return False, 0.0

    except Exception as e:
        print("[BLOCKCHAIN ERROR] Неожиданная ошибка: " + str(e))
        return False, 0.0


async def _check_transaction(
    session: aiohttp.ClientSession,
    tx_hash: str,
    wallet: str,
    expected_amount: float,
    created_at: int
) -> tuple:
    """
    Проверяет конкретную транзакцию.

    Args:
        session:         aiohttp сессия (переиспользуем)
        tx_hash:         хеш транзакции
        wallet:          наш LTC кошелёк
        expected_amount: ожидаемая сумма в LTC
        created_at:      unix timestamp — транзакция должна быть новее

    Returns:
        tuple: (подходит: bool, сумма: float)
    """
    url = "https://api.blockchair.com/litecoin/dashboards/transaction/" + tx_hash

    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:

            if resp.status != 200:
                return False, 0.0

            data = await resp.json()
            tx_data = data.get("data", {}).get(tx_hash, {})

            if not tx_data:
                return False, 0.0

            tx_info = tx_data.get("transaction", {})

            # Проверяем время транзакции
            tx_time_str = tx_info.get("time", "")
            tx_timestamp = _parse_tx_time(tx_time_str)

            if tx_timestamp == 0:
                print("[BLOCKCHAIN] Не удалось распарсить время транзакции")
                return False, 0.0

            # Транзакция должна быть создана ПОСЛЕ инвойса
            if tx_timestamp < created_at:
                print(
                    "[BLOCKCHAIN] Транзакция " + tx_hash[:8] + "... старше инвойса, пропускаем"
                )
                return False, 0.0

            # Проверяем подтверждения (минимум 1)
            confirmations = tx_info.get("confirmation_span", 0)
            if confirmations == 0:
                print("[BLOCKCHAIN] Транзакция " + tx_hash[:8] + "... ещё не подтверждена")
                return False, 0.0

            # Ищем выходы (outputs) на наш кошелёк
            outputs = tx_data.get("outputs", [])
            for output in outputs:
                recipient = output.get("recipient", "")
                if recipient != wallet:
                    continue

                # Конвертируем satoshi → LTC
                value_satoshi = output.get("value", 0)
                amount_ltc = value_satoshi / 100_000_000

                print(
                    "[BLOCKCHAIN] Найден выход на наш кошелёк: " +
                    str(amount_ltc) + " LTC"
                )
                print("[BLOCKCHAIN] Ожидается: " + str(expected_amount) + " LTC")

                # Допускаем отклонение ±2% (комиссии, округление)
                tolerance = expected_amount * 0.02
                if abs(amount_ltc - expected_amount) <= tolerance:
                    print("[BLOCKCHAIN] ✅ Платёж подтверждён! " + str(amount_ltc) + " LTC")
                    return True, amount_ltc

                print(
                    "[BLOCKCHAIN] Сумма не совпадает: " +
                    str(amount_ltc) + " != " + str(expected_amount)
                )

            return False, 0.0

    except Exception as e:
        print("[BLOCKCHAIN TX ERROR] " + str(e))
        return False, 0.0


def _parse_tx_time(time_str: str) -> int:
    """
    Парсит время транзакции из формата Blockchair API.
    Формат: '2024-01-15 12:34:56'

    Returns:
        int: unix timestamp или 0 если не удалось распарсить
    """
    if not time_str:
        return 0

    try:
        import datetime
        dt = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp())
    except Exception as e:
        print("[BLOCKCHAIN] Ошибка парсинга времени '" + str(time_str) + "': " + str(e))
        return 0
