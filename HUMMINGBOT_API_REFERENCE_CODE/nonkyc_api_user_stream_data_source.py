import asyncio
import time
from typing import TYPE_CHECKING, List, Optional

from hummingbot.connector.exchange.nonkyc import nonkyc_constants as CONSTANTS, nonkyc_web_utils as web_utils
from hummingbot.connector.exchange.nonkyc.nonkyc_auth import NonkycAuth
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.core.web_assistant.connections.data_types import WSJSONRequest
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.exchange.Nonkyc.Nonkyc_exchange import NonkycExchange


class NonkycAPIUserStreamDataSource(UserStreamTrackerDataSource):

    HEARTBEAT_TIME_INTERVAL = 30.0

    _logger: Optional[HummingbotLogger] = None

    def __init__(self,
                 auth: NonkycAuth,
                 trading_pairs: List[str],
                 connector: 'NonkycExchange',
                 api_factory: WebAssistantsFactory,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN):
        super().__init__()
        self._auth: NonkycAuth = auth
        self._domain = domain
        self._api_factory = api_factory

    async def _connected_websocket_assistant(self) -> WSAssistant:
        """
        Creates an instance of WSAssistant connected to the exchange
        """

        ws: WSAssistant = await self._get_ws_assistant()
        await ws.connect(ws_url=CONSTANTS.WS_URL, ping_timeout=CONSTANTS.WS_HEARTBEAT_TIME_INTERVAL)
        await self._authenticate_ws_connection(ws)
        return ws

    async def _subscribe_channels(self, websocket_assistant: WSAssistant):
        """
        Subscribes to the trade events and diff orders events through the provided websocket connection.
        :param websocket_assistant: the websocket assistant used to connect to the exchange
        """
        subscribe_user_orders_payload = {
                 "method": CONSTANTS.WS_METHOD_SUBSCRIBE_USER_ORDERS ,
                 "params": {}
               }
        subscribe_user_balance_payload = {
                 "method": CONSTANTS.WS_METHOD_SUBSCRIBE_USER_BALANCE ,
                 "params": {}
               }
    
        subscribe_user_orders_request: WSJSONRequest = WSJSONRequest(payload=subscribe_user_orders_payload)
        await websocket_assistant.send(subscribe_user_orders_request)
        self.logger().info("Subscribed to user orders")
        subscribe_user_balance_request: WSJSONRequest = WSJSONRequest(payload=subscribe_user_balance_payload)
        await websocket_assistant.send(subscribe_user_balance_request)
        self.logger().info("Subscribed to user balance")
        pass


    async def _get_ws_assistant(self) -> WSAssistant:
        if self._ws_assistant is None:
            self._ws_assistant = await self._api_factory.get_ws_assistant()
        return self._ws_assistant


    async def _authenticate_ws_connection(self, ws: WSAssistant):
        """
        Sends the authentication message.
        :param ws: the websocket assistant used to connect to the exchange
        """
        auth_message: WSJSONRequest = WSJSONRequest(payload=self._auth.generate_ws_authentication_message())
        await ws.send(auth_message)