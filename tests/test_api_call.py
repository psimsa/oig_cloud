import aiohttp
import pytest
from bs4 import BeautifulSoup  # Pro zpracování HTML odpovědi
import time  # Import modulu time
from typing import List, Dict, Any  # Import pro typové anotace
import json  # Import pro JSON


@pytest.mark.asyncio
async def test_api_call() -> None:
    """Test API call with login and time-based nonce."""
    session = aiohttp.ClientSession()

    try:
        # Simulace přihlášení (nahraďte URL a data skutečnými hodnotami)
        login_url = "https://www.oigpower.cz/cez/inc/php/scripts/Controller.Login.php"
        login_data: Dict[str, str] = {
            "username": "horak.martin@seznam.cz",  # Nahraďte skutečnými přihlašovacími údaji
            "password": "HOmag79//",
        }
        async with session.post(login_url, data=login_data) as login_response:
            assert (
                login_response.status == 200
            ), f"Login failed: Status {login_response.status}, Response: {await login_response.text()}"
            cookies = login_response.cookies
            print(f"Login cookies: {cookies}")

        # Kontrola, zda cookies obsahují PHPSESSID
        phpsessid = cookies.get("PHPSESSID")
        if not phpsessid:
            raise AssertionError(
                "PHPSESSID cookie not found. Login may have failed or cookie name is different."
            )
        print(f"PHPSESSID found: {phpsessid.value}")

        # Načtení hlavní stránky po přihlášení (pro případné nastavení session nebo získání nonce)
        main_page_url: str = "https://www.oigpower.cz/cez/"
        print(f"Fetching main page after login: {main_page_url}")
        async with session.get(main_page_url, cookies=cookies) as main_page_response:
            assert (
                main_page_response.status == 200
            ), f"Failed to fetch main page: Status {main_page_response.status}"
            main_page_html: str = await main_page_response.text()
            print(f"Main page HTML (first 500 chars): {main_page_html[:500]}...")
            # Zde byste mohli zkusit parsovat _nonce z main_page_html, pokud tam je
            # Např. soup_main = BeautifulSoup(main_page_html, "html.parser")
            # nonce_element = soup_main.find("input", {"name": "_nonce"})
            # if nonce_element and nonce_element.get("value"):
            #     _nonce = nonce_element.get("value")
            #     print(f"Nonce found on main page: {_nonce}")
            # else:
            #     # Pokud nonce není na hlavní stránce, použijeme časově generovaný
            #     _nonce_val: int = int(time.time() * 1000)
            #     _nonce: str = str(_nonce_val)
            #     print(f"Nonce not found on main page, using time-based: {_nonce}")

        # Prozatím stále používáme časově generovaný nonce, dokud neověříme, zda je na hlavní stránce
        _nonce_val: int = int(time.time() * 1000)
        _nonce: str = str(_nonce_val)
        print(f"Generated time-based nonce (after main page fetch): {_nonce}")

        # Volání API s _nonce
        api_url: str = "https://www.oigpower.cz/cez/inc/php/scripts/Controller.Call.php"

        params: Dict[str, Any] = {
            "id": 2,
            "selector_id": "ctrl-notifs",
            "_nonce": _nonce,
        }

        # Přidání standardní User-Agent hlavičky
        headers: Dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        print(f"Calling API: {api_url} with params: {params} and headers: {headers}")
        async with session.get(
            api_url, params=params, cookies=cookies, headers=headers
        ) as api_response:
            assert (
                api_response.status == 200
            ), f"API call failed: Status {api_response.status}, Response: {await api_response.text()}"

            # Odpověď je JSON pole, kde HTML je třetí prvek
            response_json_data: Any = await api_response.json()
            print(f"Raw API JSON response: {response_json_data}")

            # Ověření, že vnější odpověď je seznam a obsahuje alespoň jeden prvek (vnitřní seznam)
            assert (
                isinstance(response_json_data, list) and len(response_json_data) > 0
            ), "Odpověď API není seznam nebo je prázdná."

            # Vnitřní seznam by měl obsahovat HTML jako třetí prvek
            inner_list: Any = response_json_data[0]
            assert (
                isinstance(inner_list, list) and len(inner_list) > 2
            ), "Vnitřní struktura odpovědi API není seznam s očekávanou délkou (chybí HTML prvek)."

            html_content_from_json: str = inner_list[2]
            assert isinstance(
                html_content_from_json, str
            ), "Třetí prvek v JSON odpovědi není řetězec (očekávané HTML)."

            print(f"HTML content from JSON (length: {len(html_content_from_json)}):")
            print(
                html_content_from_json[:1000] + "..."
                if len(html_content_from_json) > 1000
                else html_content_from_json
            )

            # Zpracování HTML odpovědi pomocí BeautifulSoup (pro notifikace)
            soup = BeautifulSoup(html_content_from_json, "html.parser")

            notifications_container = soup.find(
                "div", {"id": "ctrl-notifs", "x:controller:id": "2"}
            )
            assert (
                notifications_container is not None
            ), "Hlavní kontejner pro notifikace ('ctrl-notifs') nebyl v HTML obsahu nalezen."

            folder_elements = notifications_container.find_all(
                "div", class_="folder"
            )  # Hledáme uvnitř kontejneru
            print(f"Nalezeno {len(folder_elements)} elementů 'folder'.")

            extracted_data: List[Dict[str, str]] = []
            for folder in folder_elements:
                date_element = folder.find("div", class_="date")
                row_2_element = folder.find("div", class_="row-2")
                body_element = folder.find("div", class_="body")

                date: str = date_element.text.strip() if date_element else "N/A"
                summary: str = row_2_element.text.strip() if row_2_element else "N/A"
                details: str = body_element.text.strip() if body_element else "N/A"

                extracted_data.append(
                    {
                        "date": date,
                        "summary": summary,
                        "details": details,
                    }
                )

            # Ověření a výpis extrahovaných dat
            # Tento assert očekává, že budou nalezeny nějaké notifikace.
            # Pokud je v pořádku, že notifikace mohou být prázdné, tento assert by měl být upraven.
            assert extracted_data, (
                "Nebyla extrahována žádná notifikační data (elementy 'div.folder'). "
                "Pokud je to očekávané (žádné nové notifikace), upravte tento assert."
            )

            print(
                f"\n--- Extrahovaná notifikační data ({len(extracted_data)} položek) ---"
            )
            for data_item in extracted_data:
                print(f"Datum: {data_item['date']}")
                print(f"Shrnutí: {data_item['summary']}")
                print(f"Detaily: {data_item['details']}")
                print("-" * 40)

            # Další možné asserty pro kontrolu obsahu, pokud znáte očekávané hodnoty:
            # if extracted_data:
            #     assert extracted_data[0]['date'] != "N/A", "Datum první notifikace by nemělo být 'N/A'."
            #     assert extracted_data[0]['summary'], "Shrnutí první notifikace by nemělo být prázdné."

    finally:
        await session.close()
