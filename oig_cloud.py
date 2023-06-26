import json
import logging
import aiohttp


class OigCloud:
    base_url = "https://www.oigpower.cz/cez/"
    login_url = "inc/php/scripts/Login.php"
    get_stats_url = "json.php"

    username: str = None
    password: str = None

    phpsessid: str = None

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password
        self.last_state = None
        self.logger = logging.getLogger(__name__)

    async def authenticate(self) -> bool:
        login_command = {"email": self.username, "password": self.password}

        async with (aiohttp.ClientSession()) as session:
            async with session.post(
                self.base_url + self.login_url,
                data=json.dumps(login_command),
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status == 200:
                    responsecontent = await response.text()
                    if responsecontent == '[[2,"",false]]':
                        self.phpsessid = (
                            session.cookie_jar.filter_cookies(self.base_url)
                            .get("PHPSESSID")
                            .value
                        )
                        return True
                return False

    def get_session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(headers={"Cookie": f"PHPSESSID={self.phpsessid}"})

    async def get_stats(self) -> object:
        to_return: object = None
        try:
            to_return = await self.get_stats_internal()
        except:
            if await self.authenticate():
                to_return = await self.get_stats_internal()
        return to_return

    async def get_stats_internal(self, dependent: bool = False) -> object:
        to_return: object = None
        async with self.get_session() as session:
            async with session.get(self.base_url + self.get_stats_url) as response:
                if response.status == 200:
                    to_return = await response.json()
                    # the response should be a json dictionary, otherwise it's an error
                    if not isinstance(to_return, dict) and not dependent:
                        self.logger.info("Retrying with authentication")
                        if await self.authenticate():
                            second_try = await self.get_stats_internal(True)
                            if not isinstance(second_try, dict):
                                self.logger.warning(f"Error: {second_try}")
                                return None
                            else:
                                to_return = second_try
                        else:
                            return None
                self.last_state = to_return
            return to_return
