# utils/blockchain.py
# Проверка LTC платежей
# Основной API: BlockCypher (2000 запросов/час бесплатно, без ключа)
# Резервный API:  Bitaps (без ключа)
#
# ИЗМЕНЕНИЯ vs старая версия:
# 1. Убран Blockchair (возвращал 430 — Too Many Requests)
# 2. Убран aiohttp + asyncio — на Android/Pydroid это нестабильно
#    Заменён на синхронный requests в обычной функции
# 3. monitor_payment в callback.py вызывает check_payment напрямую без asyncio.run()
# 4. Логика та же: ищем транзакции ПОСЛЕ создания инвойса с суммой ±2%

import time
import requests

# Тайм-аут HTTP запросов
REQUEST_TIMEOUT = 15


# ─────────────────────────────────────────────
# Публичная функция — вызывается из callback.py
# ─────────────────────────────────────────────

def check_payment(wallet: str, expected_amount: float, created_at: int = None) -> tuple:
    """
    Проверяет поступление LTC платежа на кошелёк.

    Логика:
        1. Пробуем BlockCypher (основной)
        2. Если BlockCypher недоступен — пробуем Bitaps (резервный)
        3. Ищем транзакцию ПОСЛЕ created_at с суммой ±2%

    Args:
        wallet:          LTC адрес кошелька
        expected_amount: ожидаемая сумма в LTC
        created_at:      unix timestamp создания инвойса
                         (если None — берём текущее время минус 10 минут)

    Returns:
        tuple: (найден: bool, сумма: float)
    """
    if created_at is None:
        created_at = int(time.time()) - 600  # 10 минут назад

    print("[BLOCKCHAIN] Проверяем " + wallet + " ожидаем " + str(expected_amount) + " LTC")

    # Попытка 1 — BlockCypher
    result = _check_blockcypher(wallet, expected_amount, created_at)
    if result is not None:
        return result

    # Попытка 2 — Bitaps
    print("[BLOCKCHAIN] BlockCypher недоступен, пробуем Bitaps...")
    result = _check_bitaps(wallet, expected_amount, created_at)
    if result is not None:
        return result

    print("[BLOCKCHAIN] Все API недоступны")
    return False, 0.0


# ─────────────────────────────────────────────
# BlockCypher API
# ─────────────────────────────────────────────

def _check_blockcypher(wallet: str, expected_amount: float, created_at: int):
    """
    Проверка через BlockCypher.
    Документация: https://www.blockcypher.com/dev/litecoin/

    Returns:
        tuple (found, amount) или None если API недоступен
    """
    try:
        # Получаем список транзакций адреса с деталями
        url = "https://api.blockcypher.com/v1/ltc/main/addrs/" + wallet + "/full"
        params = {
            "limit": 10,       # последние 10 транзакций
            "confirmations": 1  # только подтверждённые
        }

        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

        if resp.status_code == 429:
            print("[BLOCKCHAIN] BlockCypher: лимит запросов (429)")
            return None

        if resp.status_code == 404:
            # Новый кошелёк без транзакций — нормальная ситуация
            print("[BLOCKCHAIN] BlockCypher: кошелёк пустой (404)")
            return False, 0.0

        if resp.status_code != 200:
            print("[BLOCKCHAIN] BlockCypher: статус " + str(resp.status_code))
            return None

        data = resp.json()
        txs = data.get("txs", [])

        if not txs:
            print("[BLOCKCHAIN] BlockCypher: транзакций нет")
            return False, 0.0

        print("[BLOCKCHAIN] BlockCypher: найдено транзакций: " + str(len(txs)))

        for tx in txs:
            result = _parse_blockcypher_tx(tx, wallet, expected_amount, created_at)
            if result is not None:
                return result

        return False, 0.0

    except requests.exceptions.Timeout:
        print("[BLOCKCHAIN] BlockCypher: таймаут")
        return None
    except requests.exceptions.ConnectionError:
        print("[BLOCKCHAIN] BlockCypher: нет соединения")
        return None
    except Exception as e:
        print("[BLOCKCHAIN] BlockCypher ошибка: " + str(e))
        return None


def _parse_blockcypher_tx(tx: dict, wallet: str,
                           expected_amount: float, created_at: int):
    """
    Разбирает одну транзакцию BlockCypher.

    Returns:
        (True, amount) если подходит
        (False, 0.0) если не подходит
        None если нужно пропустить (нет времени и т.д.)
    """
    # Проверяем подтверждения
    confirmations = tx.get("confirmations", 0)
    if confirmations < 1:
        return None  # Неподтверждённая — пропускаем

    # Проверяем время транзакции
    received_str = tx.get("confirmed") or tx.get("received", "")
    if received_str:
        tx_time = _parse_iso_time(received_str)
        if tx_time and tx_time < created_at:
            # Транзакция старше нашего инвойса — пропускаем
            return None

    # Ищем выходы (outputs) на наш кошелёк
    outputs = tx.get("outputs", [])
    for output in outputs:
        addresses = output.get("addresses", [])
        if wallet not in addresses:
            continue

        # Сатоши → LTC
        value_satoshi = output.get("value", 0)
        amount_ltc = value_satoshi / 100_000_000

        print("[BLOCKCHAIN] Выход на наш кошелёк: " + str(amount_ltc) + " LTC")

        # Допуск ±2%
        tolerance = expected_amount * 0.02
        if abs(amount_ltc - expected_amount) <= tolerance:
            print("[BLOCKCHAIN] BlockCypher: платёж найден! " + str(amount_ltc) + " LTC")
            return True, amount_ltc

        print("[BLOCKCHAIN] Сумма не совпадает: " + str(amount_ltc) + " != " + str(expected_amount))

    return False, 0.0


# ─────────────────────────────────────────────
# Bitaps API (резервный)
# ─────────────────────────────────────────────

def _check_bitaps(wallet: str, expected_amount: float, created_at: int):
    """
    Резервная проверка через Bitaps API.
    Документация: https://ltc.bitaps.com/api

    Returns:
        tuple (found, amount) или None если API недоступен
    """
    try:
        url = "https://ltc.bitaps.com/api/v1/blockchain/address/" + wallet + "/transactions"
        params = {
            "limit": 10,
            "page": 0
        }

        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

        if resp.status_code != 200:
            print("[BLOCKCHAIN] Bitaps: статус " + str(resp.status_code))
            return None

        data = resp.json()
        tx_list = data.get("data", {}).get("list", [])

        if not tx_list:
            print("[BLOCKCHAIN] Bitaps: транзакций нет")
            return False, 0.0

        print("[BLOCKCHAIN] Bitaps: найдено транзакций: " + str(len(tx_list)))

        for tx in tx_list:
            result = _parse_bitaps_tx(tx, wallet, expected_amount, created_at)
            if result is not None and result[0]:
                return result

        return False, 0.0

    except requests.exceptions.Timeout:
        print("[BLOCKCHAIN] Bitaps: таймаут")
        return None
    except requests.exceptions.ConnectionError:
        print("[BLOCKCHAIN] Bitaps: нет соединения")
        return None
    except Exception as e:
        print("[BLOCKCHAIN] Bitaps ошибка: " + str(e))
        return None


def _parse_bitaps_tx(tx: dict, wallet: str,
                     expected_amount: float, created_at: int):
    """
    Разбирает одну транзакцию Bitaps.

    Returns:
        (True, amount) если подходит, иначе (False, 0.0)
    """
    # Проверяем подтверждения
    confirmations = tx.get("confirmations", 0)
    if confirmations < 1:
        return False, 0.0

    # Проверяем время транзакции (unix timestamp в Bitaps)
    tx_time = tx.get("time", 0)
    if tx_time and tx_time < created_at:
        return False, 0.0

    # Ищем только входящие outputs для нашего адреса
    outputs = tx.get("outputs", [])
    for output in outputs:
        addr = output.get("address", "")
        if addr != wallet:
            continue

        value_satoshi = output.get("value", 0)
        amount_ltc = value_satoshi / 100_000_000

        print("[BLOCKCHAIN] Bitaps выход: " + str(amount_ltc) + " LTC")

        tolerance = expected_amount * 0.02
        if abs(amount_ltc - expected_amount) <= tolerance:
            print("[BLOCKCHAIN] Bitaps: платёж найден! " + str(amount_ltc) + " LTC")
            return True, amount_ltc

    return False, 0.0


# ─────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────

def _parse_iso_time(time_str: str) -> int | None:
    """
    Парсит ISO 8601 время в unix timestamp.
    Форматы: '2024-01-15T10:30:00Z' или '2024-01-15T10:30:00.000Z'
    """
    if not time_str:
        return None
    try:
        import datetime
        # Убираем миллисекунды и Z на конце
        clean = time_str[:19].replace("T", " ")
        dt = datetime.datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
        # Добавляем UTC timezone
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp())
    except Exception as e:
        print("[BLOCKCHAIN] Ошибка парсинга времени '" + str(time_str) + "': " + str(e))
        return None


def get_wallet_balance(wallet: str) -> float | None:
    """
    Получает текущий баланс кошелька в LTC.
    Используется для отладки, не для проверки платежей.
    """
    try:
        url = "https://api.blockcypher.com/v1/ltc/main/addrs/" + wallet + "/balance"
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            balance = data.get("balance", 0) / 100_000_000
            return balance
    except Exception as e:
        print("[BLOCKCHAIN] Ошибка получения баланса: " + str(e))
    return None
