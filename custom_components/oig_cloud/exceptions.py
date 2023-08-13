from homeassistant.exceptions import IntegrationError


class OigApiCallError(IntegrationError):
    """
    Raised when there is an error making a call to the OIG API.
    """

    def __init__(
        self, message: str, status_code: int, response: dict | str | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class OigNoTelemetryException(IntegrationError):
    """
    Raised when telemetry is disabled but required for operation.
    """

    def __init__(self, message: str):
        super().__init__(message)
