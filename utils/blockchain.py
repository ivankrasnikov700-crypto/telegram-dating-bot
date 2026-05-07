import aiohttp
import asyncio


async def check_payment(
    wallet: str,
    expected_amount: float,
    timeout: int = 1
) -> tuple:
    url = "https://api.blockchair.com/litecoin/dashboards/address/" + wallet

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:

                status = resp.status
                if status != 200:
                    print("[BLOCKCHAIN] API статус: " + str(status))
                    return False, 0.0

                data = await resp.json()
                address_data = data.get("data", {}).get(wallet, {})
                address_info = address_data.get("address", {})

                if not address_info:
                    return False, 0.0

                received_satoshi = address_info.get("received", 0)
                amount_ltc = received_satoshi / 100_000_000

                print("[BLOCKCHAIN] Получено: " + str(amount_ltc) + " LTC")
                print("[BLOCKCHAIN] Ожидается: " + str(expected_amount) + " LTC")

                tolerance = expected_amount * 0.02

                if abs(amount_ltc - expected_amount) <= tolerance:
                    print("[BLOCKCHAIN] Платёж подтверждён!")
                    return True, amount_ltc

                return False, 0.0

    except asyncio.TimeoutError:
        print("[BLOCKCHAIN ERROR] Timeout")
        return False, 0.0

    except Exception as e:
        print("[BLOCKCHAIN ERROR] " + str(e))
        return False, 0.0
