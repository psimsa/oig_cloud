class OIGCloudConfig:
    def __init__(self, username: str, password: str, phpsessid: str | None = None):
        self.username = username
        self.password = password
        self.phpsessid = phpsessid
