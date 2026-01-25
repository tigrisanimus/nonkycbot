from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

DEFAULT_DOMAIN = "com"
EXCHANGE_NAME = "nonkyc"

# Base urls
REST_URL = "https://api.nonkyc.io/api/"
WS_URL = "wss://api.nonkyc.io"

API_VERSION = "v2"

BROKER_ID = "hummingbot"
HBOT_ORDER_ID_PREFIX = "HBOT-"
MAX_ORDER_ID_LEN = 32

# Public Nonkyc API endpoints
SERVER_TIME_API_URL = "https://nonkyc.io/api/v2/getservertime"
TICKER_INFO_PATH_URL = "/ticker"
TICKER_BOOK_PATH_URL = "/tickers"
MARKETS_INFO_PATH_URL = "/market/getlist"
PING_PATH_URL = "/info"
SUPPORTED_SYMBOL_PATH_URL = "/asset/getlist"
ORDERBOOK_SNAPSHOT_PATH_URL = "/orderbook"

# Private Nonkyc API endpoints
USER_BALANCES_PATH_URL = "/balances"
USER_TRADES_PATH_URL = "/gettrades"
USER_TRADES_SINCE_A_TIMESTAMP_PATH_URL = "/gettradessince"

CREATE_ORDER_PATH_URL = "/createorder"
CANCEL_ORDER_PATH_URL = "/cancelorder"
ORDER_INFO_PATH_URL = "/getorder"

# Ws public methods
WS_METHOD_SUBSCRIBE_ORDERBOOK = "subscribeOrderbook"
WS_METHOD_SUBSCRIBE_TRADES = "subscribeTrades"

# Ws private methods
WS_METHOD_SUBSCRIBE_USER_ORDERS = "subscribeReports"
WS_METHOD_SUBSCRIBE_USER_BALANCE = "subscribeBalances"


# Websocket event types
DIFF_EVENT_TYPE = "updateOrderbook"
TRADE_EVENT_TYPE = "updateTrades"

WS_HEARTBEAT_TIME_INTERVAL = 30

# Rate Limit time intervals in seconds
ONE_MINUTE = 60
ONE_SECOND = 1
ONE_DAY = 86400

# Order params
SIDE_BUY = "buy"
SIDE_SELL = "sell"

ORDER_STATE = {
    "New": OrderState.OPEN,
    "Active": OrderState.OPEN,
    "Filled": OrderState.FILLED,
    "Partly Filled": OrderState.PARTIALLY_FILLED,
    "Cancelled": OrderState.CANCELED,
}

# Rate Limit Type
REQUEST_WEIGHT = "REQUEST_WEIGHT"
ORDERS = "ORDERS"
ORDERS_24HR = "ORDERS_24HR"
RAW_REQUESTS = "RAW_REQUESTS"

MAX_REQUEST = 5000

RATE_LIMITS = [
    # Pools
    RateLimit(limit_id=REQUEST_WEIGHT, limit=6000, time_interval=ONE_MINUTE),
    RateLimit(limit_id=ORDERS, limit=50, time_interval=10 * ONE_SECOND),
    RateLimit(limit_id=ORDERS_24HR, limit=160000, time_interval=ONE_DAY),
    RateLimit(limit_id=RAW_REQUESTS, limit=61000, time_interval=5 * ONE_MINUTE),
    # Weighted Limits
    RateLimit(
        limit_id=TICKER_INFO_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 2),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=TICKER_BOOK_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 4),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=MARKETS_INFO_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 20),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=ORDERBOOK_SNAPSHOT_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 100),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=USER_BALANCES_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 20),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=SERVER_TIME_API_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 1),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=PING_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 1),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=USER_TRADES_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 20),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=USER_TRADES_SINCE_A_TIMESTAMP_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 20),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=CREATE_ORDER_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 4),
            LinkedLimitWeightPair(ORDERS, 1),
            LinkedLimitWeightPair(ORDERS_24HR, 1),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=CANCEL_ORDER_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 4),
            LinkedLimitWeightPair(ORDERS, 1),
            LinkedLimitWeightPair(ORDERS_24HR, 1),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
    RateLimit(
        limit_id=ORDER_INFO_PATH_URL,
        limit=MAX_REQUEST,
        time_interval=ONE_MINUTE,
        linked_limits=[
            LinkedLimitWeightPair(REQUEST_WEIGHT, 4),
            LinkedLimitWeightPair(ORDERS, 1),
            LinkedLimitWeightPair(ORDERS_24HR, 1),
            LinkedLimitWeightPair(RAW_REQUESTS, 1),
        ],
    ),
]

ORDER_NOT_EXIST_ERROR_CODE = 20002
ORDER_NOT_EXIST_MESSAGE = "Order not found"

UNKNOWN_ORDER_ERROR_CODE = 20002
UNKNOWN_ORDER_MESSAGE = "Active order not found for cancellation"
