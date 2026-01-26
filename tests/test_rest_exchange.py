from nonkyc_client.rest import RestError, RestRequest
from nonkyc_client.rest_exchange import NonkycRestExchangeClient


class NotFoundRestClient:
    def __init__(self) -> None:
        self.requests: list[RestRequest] = []

    def send(self, request: RestRequest) -> dict[str, object]:
        self.requests.append(request)
        raise RestError("HTTP error 404: Not Found")


def test_list_open_orders_returns_empty_on_not_found() -> None:
    client = NonkycRestExchangeClient(NotFoundRestClient())

    open_orders = client.list_open_orders("BTC_USDT")

    assert open_orders == []
