"""Pydantic schemas for NonKYC API with comprehensive validation."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OrderSide(str, Enum):
    """Order side enum."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type enum."""

    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(str, Enum):
    """Order status enum."""

    ACTIVE = "Active"
    CANCELLED = "Cancelled"
    FILLED = "Filled"
    PARTLY_FILLED = "Partly Filled"


class TradeSide(str, Enum):
    """Trade side enum."""

    BUY = "buy"
    SELL = "sell"


class MarketType(str, Enum):
    """Market type enum."""

    MARKET = "market"
    LIQUIDITY_POOL = "liquiditypool"


# ============================================================================
# Asset Schemas
# ============================================================================


class TokenOfSchema(BaseModel):
    """Token parent reference schema."""

    model_config = ConfigDict(extra="allow")

    schema_: str | None = Field(None, alias="schema")


class AssetSchema(BaseModel):
    """Complete Asset schema matching NonKYC API.

    Represents a cryptocurrency or token with all trading parameters.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(..., description="Internal ID")
    ticker: str = Field(..., description="Ticker code")
    name: str = Field(..., description="Name of asset")
    logo: str | None = Field(None, description="Logo filename")
    is_active: bool = Field(True, alias="isActive", description="Is asset active")
    is_token: bool = Field(False, alias="isToken", description="Is asset a token")
    token_of: TokenOfSchema | None = Field(None, alias="tokenOf")
    token_details: dict[str, Any] | None = Field(None, alias="tokenDetails")
    use_parent_address: bool = Field(
        False,
        alias="useParentAddress",
        description="Uses same deposit address as parent",
    )
    usd_value: str | None = Field(None, alias="usdValue", description="Value in USD")

    # Deposit settings
    deposit_active: bool = Field(True, alias="depositActive")
    deposit_notes: str | None = Field(None, alias="depositNotes")
    deposit_pay_id: bool = Field(False, alias="depositPayId")

    # Withdrawal settings
    withdrawal_active: bool = Field(True, alias="withdrawalActive")
    withdrawal_notes: str | None = Field(None, alias="withdrawalNotes")
    withdrawal_payid: bool = Field(False, alias="withdrawalPayid")
    withdrawal_payid_required: bool = Field(False, alias="withdrawalPayidRequired")

    # Network parameters
    confirms_required: int = Field(0, alias="confirmsRequired", ge=0)
    withdraw_decimals: int = Field(8, alias="withdrawDecimals", ge=0, le=18)
    withdraw_fee: str | None = Field(None, alias="withdrawFee")

    # External links
    explorer: str | None = None
    explorer_txid: str | None = Field(None, alias="explorerTxid")
    explorer_address: str | None = Field(None, alias="explorerAddress")
    website: str | None = None
    coin_market_cap: str | None = Field(None, alias="coinMarketCap")
    coin_gecko: str | None = Field(None, alias="coinGecko")

    # Validation patterns
    address_regex: str | None = Field(None, alias="addressRegEx")
    payid_regex: str | None = Field(None, alias="payidRegEx")

    # Social
    social_community: dict[str, Any] | None = Field(None, alias="socialCommunity")

    # Timestamps
    created_at: int | None = Field(None, alias="createdAt")
    updated_at: int | None = Field(None, alias="updatedAt")

    @field_validator("withdraw_fee", "usd_value", mode="before")
    @classmethod
    def validate_decimal_string(cls, v: Any) -> str | None:
        """Validate decimal strings are valid."""
        if v is None or v == "":
            return None
        try:
            # Ensure it can be parsed as Decimal
            Decimal(str(v))
            return str(v)
        except Exception:
            raise ValueError(f"Invalid decimal string: {v}")


# ============================================================================
# Market Schemas
# ============================================================================


class MarketAssetReference(BaseModel):
    """Embedded asset reference in market."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    schema_: AssetSchema | None = Field(None, alias="schema")


class MarketSchema(BaseModel):
    """Complete Market schema matching NonKYC API."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    symbol: str
    primary_asset: MarketAssetReference | None = Field(None, alias="primaryAsset")
    secondary_asset: MarketAssetReference | None = Field(None, alias="secondaryAsset")
    last_price: str | None = Field(None, alias="lastPrice")
    high_price: str | None = Field(None, alias="highPrice")
    low_price: str | None = Field(None, alias="lowPrice")
    volume: str | None = None
    line_chart: str | None = Field(None, alias="lineChart")
    last_trade_at: int | None = Field(None, alias="lastTradeAt")
    price_decimals: int = Field(8, alias="priceDecimals", ge=0, le=18)
    quantity_decimals: int = Field(8, alias="quantityDecimals", ge=0, le=18)
    is_active: bool = Field(True, alias="isActive")


class LiquidityPoolSchema(BaseModel):
    """Liquidity pool schema."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    symbol: str
    primary_asset: MarketAssetReference | None = Field(None, alias="primaryAsset")
    secondary_asset: MarketAssetReference | None = Field(None, alias="secondaryAsset")
    last_price: str | None = Field(None, alias="lastPrice")
    high_price: str | None = Field(None, alias="highPrice")
    low_price: str | None = Field(None, alias="lowPrice")
    volume: str | None = None
    line_chart: str | None = Field(None, alias="lineChart")
    last_trade_at: int | None = Field(None, alias="lastTradeAt")
    is_active: bool = Field(True, alias="isActive")


# ============================================================================
# Balance & Account Schemas
# ============================================================================


class BalanceSchema(BaseModel):
    """Account balance schema with validation."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    asset: str = Field(..., description="Ticker of asset")
    name: str | None = Field(None, description="Name of asset")
    available: str = Field(..., description="Available balance")
    pending: str = Field("0", description="Pending deposits")
    held: str = Field("0", description="Balance held in orders")
    assetid: str | None = Field(None, description="Asset ID code")

    @field_validator("available", "pending", "held", mode="before")
    @classmethod
    def validate_balance_amount(cls, v: Any) -> str:
        """Validate balance amounts are valid decimals."""
        if v is None:
            return "0"
        try:
            decimal_val = Decimal(str(v))
            if decimal_val < 0:
                raise ValueError("Balance cannot be negative")
            return str(v)
        except Exception as e:
            raise ValueError(f"Invalid balance amount: {v}") from e


class DepositAddressSchema(BaseModel):
    """Deposit address schema."""

    model_config = ConfigDict(extra="allow")

    address: str
    paymentid: str | None = None
    ticker: str
    network: str | None = None


# ============================================================================
# Order Schemas
# ============================================================================


class MarketReference(BaseModel):
    """Market reference in order responses."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    schema_: dict[str, Any] | None = Field(None, alias="schema")
    id: str | None = None
    symbol: str | None = None


class OrderSchema(BaseModel):
    """Complete order schema."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    user_provided_id: str | None = Field(None, alias="userProvidedId")
    market: MarketReference | None = None
    symbol: str | None = None
    side: OrderSide
    type: OrderType
    price: str | None = None
    quantity: str
    executed_quantity: str = Field("0", alias="executedQuantity")
    remain_quantity: str | None = Field(None, alias="remainQuantity")
    remain_total: str | None = Field(None, alias="remainTotal")
    remain_total_with_fee: str | None = Field(None, alias="remainTotalWithFee")
    last_trade_at: int | None = Field(None, alias="lastTradeAt")
    status: OrderStatus
    is_active: bool = Field(True, alias="isActive")
    created_at: int | None = Field(None, alias="createdAt")
    updated_at: int | None = Field(None, alias="updatedAt")
    timestamp: int | None = None  # Alternative field name

    @field_validator("price", "quantity", "executed_quantity", mode="before")
    @classmethod
    def validate_price_quantity(cls, v: Any) -> str:
        """Validate price/quantity are valid decimals."""
        if v is None:
            return "0"
        try:
            decimal_val = Decimal(str(v))
            if decimal_val < 0:
                raise ValueError("Value cannot be negative")
            return str(v)
        except Exception as e:
            raise ValueError(f"Invalid decimal value: {v}") from e


class OrderRequestSchema(BaseModel):
    """Order creation request schema."""

    model_config = ConfigDict(populate_by_name=True)

    symbol: str
    side: OrderSide
    type: OrderType
    quantity: str
    price: str | None = None
    user_provided_id: str | None = Field(None, alias="userProvidedId")
    strict_validate: bool | None = Field(None, alias="strictValidate")

    @field_validator("quantity", "price", mode="before")
    @classmethod
    def validate_amounts(cls, v: Any) -> str | None:
        """Validate amounts are valid decimals."""
        if v is None:
            return None
        try:
            decimal_val = Decimal(str(v))
            if decimal_val <= 0:
                raise ValueError("Amount must be positive")
            return str(v)
        except Exception as e:
            raise ValueError(f"Invalid amount: {v}") from e


class OrderCancelRequestSchema(BaseModel):
    """Order cancellation request."""

    id: str


class OrderCancelResultSchema(BaseModel):
    """Order cancellation result."""

    model_config = ConfigDict(extra="allow")

    success: bool
    id: str | None = None
    ids: list[str] | None = None


# ============================================================================
# Trade Schemas
# ============================================================================


class TradeSchema(BaseModel):
    """Trade execution schema."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    trade_id: str | None = Field(None, alias="trade_id")
    market: MarketReference | None = None
    orderid: str | None = None
    order_id: str | None = None
    symbol: str | None = None
    side: TradeSide | None = None
    triggered_by: TradeSide | None = Field(None, alias="triggeredBy")
    price: str
    quantity: str
    base_volume: str | None = Field(None, alias="base_volume")
    target_volume: str | None = Field(None, alias="target_volume")
    fee: str = "0"
    total_with_fee: str | None = Field(None, alias="totalWithFee")
    alternate_fee_asset: str | None = Field(None, alias="alternateFeeAsset")
    alternate_fee: str | None = Field(None, alias="alternateFee")
    timestamp: int | None = None
    trade_timestamp: str | None = Field(None, alias="trade_timestamp")
    created_at: int | None = Field(None, alias="createdAt")
    updated_at: int | None = Field(None, alias="updatedAt")
    type: str | None = None  # "buy" or "sell" for public trades

    @field_validator("price", "quantity", "fee", mode="before")
    @classmethod
    def validate_amounts(cls, v: Any) -> str:
        """Validate amounts are valid decimals."""
        if v is None:
            return "0"
        try:
            decimal_val = Decimal(str(v))
            if decimal_val < 0:
                raise ValueError("Amount cannot be negative")
            return str(v)
        except Exception as e:
            raise ValueError(f"Invalid amount: {v}") from e


class PoolTradeSchema(BaseModel):
    """Liquidity pool trade schema."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    pool: dict[str, Any] | None = None
    side: TradeSide
    price: str
    quantity: str
    fee: str = "0"
    total_with_fee: str | None = Field(None, alias="totalWithFee")
    created_at: int | None = Field(None, alias="createdAt")
    updated_at: int | None = Field(None, alias="updatedAt")


# ============================================================================
# OrderBook Schemas
# ============================================================================


class OrderBookLevelSchema(BaseModel):
    """Order book price level."""

    model_config = ConfigDict(extra="allow")

    price: str
    numberprice: float | None = None
    quantity: str

    @field_validator("price", "quantity", mode="before")
    @classmethod
    def validate_amounts(cls, v: Any) -> str:
        """Validate amounts are valid decimals."""
        try:
            Decimal(str(v))
            return str(v)
        except Exception as e:
            raise ValueError(f"Invalid amount: {v}") from e


class OrderBookSchema(BaseModel):
    """Order book snapshot schema."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    marketid: str | None = None
    ticker_id: str | None = Field(None, alias="ticker_id")
    symbol: str
    timestamp: int | str | None = None
    sequence: str | None = None
    bids: list[OrderBookLevelSchema] = Field(default_factory=list)
    asks: list[OrderBookLevelSchema] = Field(default_factory=list)


# ============================================================================
# Ticker Schemas
# ============================================================================


class TickerSchema(BaseModel):
    """Market ticker schema."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    ticker_id: str = Field(..., alias="ticker_id")
    type: MarketType | None = None
    base_currency: str | None = Field(None, alias="base_currency")
    target_currency: str | None = Field(None, alias="target_currency")
    symbol: str | None = None
    last_price: str | None = Field(None, alias="last_price")
    lastPrice: str | None = None
    base_volume: str | None = Field(None, alias="base_volume")
    target_volume: str | None = Field(None, alias="target_volume")
    volume: str | None = None
    bid: str | None = None
    ask: str | None = None
    high: str | None = None
    low: str | None = None
    previous_day_price: str | None = Field(None, alias="previous_day_price")

    @model_validator(mode="after")
    def normalize_last_price(self) -> "TickerSchema":
        """Normalize last_price from various field names."""
        if self.last_price is None and self.lastPrice is not None:
            self.last_price = self.lastPrice
        return self


# ============================================================================
# Candlestick Schemas
# ============================================================================


class CandlestickSchema(BaseModel):
    """Candlestick bar schema."""

    time: int
    close: float
    open: float
    high: float
    low: float
    volume: float


class CandlesticksResponse(BaseModel):
    """Candlesticks response with metadata."""

    bars: list[CandlestickSchema]
    meta: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Deposit & Withdrawal Schemas
# ============================================================================


class DepositSchema(BaseModel):
    """Deposit transaction schema."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    address: str
    paymentid: str | None = None
    ticker: str
    childticker: str | None = None
    quantity: str
    status: str
    transactionid: str | None = None
    isposted: bool = False
    isreversed: bool = False
    confirmations: int = 0
    firstseenat: str | None = None

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v: Any) -> str:
        """Validate quantity is valid decimal."""
        try:
            decimal_val = Decimal(str(v))
            if decimal_val < 0:
                raise ValueError("Quantity cannot be negative")
            return str(v)
        except Exception as e:
            raise ValueError(f"Invalid quantity: {v}") from e


class WithdrawalSchema(BaseModel):
    """Withdrawal transaction schema."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    address: str
    paymentid: str | None = None
    ticker: str
    childticker: str | None = None
    quantity: str
    fee: str
    feecurrency: str | None = None
    status: str
    transactionid: str | None = None
    issent: bool = False
    sentat: str | None = None
    isconfirmed: bool = False
    requestedat: str | None = None

    @field_validator("quantity", "fee", mode="before")
    @classmethod
    def validate_amounts(cls, v: Any) -> str:
        """Validate amounts are valid decimals."""
        try:
            decimal_val = Decimal(str(v))
            if decimal_val < 0:
                raise ValueError("Amount cannot be negative")
            return str(v)
        except Exception as e:
            raise ValueError(f"Invalid amount: {v}") from e


class WithdrawalRequestSchema(BaseModel):
    """Withdrawal creation request."""

    ticker: str
    quantity: str
    address: str
    paymentid: str | None = None

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v: Any) -> str:
        """Validate quantity is positive decimal."""
        try:
            decimal_val = Decimal(str(v))
            if decimal_val <= 0:
                raise ValueError("Quantity must be positive")
            return str(v)
        except Exception as e:
            raise ValueError(f"Invalid quantity: {v}") from e


# ============================================================================
# Exchange Info Schemas
# ============================================================================


class InfoSchema(BaseModel):
    """Exchange information schema."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: str | None = None
    location: str | None = None
    logo: str | None = None
    website: str | None = None
    twitter: str | None = None
    version: str | None = None
    capability: dict[str, Any] = Field(default_factory=dict)


class PairSchema(BaseModel):
    """Trading pair schema."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    ticker_id: str = Field(..., alias="ticker_id")
    base: str
    target: str
    type: MarketType


class MarketsListingSchema(BaseModel):
    """Market listing schema."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    base: str
    quote: str
    type: str
    market_url: str | None = Field(None, alias="market_url")
    active: str | None = None
    description: str | None = None


# ============================================================================
# Error Schemas
# ============================================================================


class ApiErrorCode(int, Enum):
    """NonKYC API error codes."""

    # General errors
    UNKNOWN_ERROR = 400
    METHOD_NOT_FOUND = 402
    FORBIDDEN = 403
    RATE_LIMIT = 429
    INTERNAL_ERROR = 500
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504

    # Auth errors
    AUTH_REQUIRED = 1001
    AUTH_FAILED = 1002
    API_KEY_FORBIDDEN = 1003
    UNSUPPORTED_AUTH = 1004

    # Resource errors
    SYMBOL_NOT_FOUND = 2001
    CURRENCY_NOT_FOUND = 2002

    # Trading errors
    VALIDATION_ERROR = 10001
    INSUFFICIENT_FUNDS = 20001
    ORDER_NOT_FOUND = 20002
    LIMIT_EXCEEDED = 20003
    TRANSACTION_NOT_FOUND = 20004
    PAYOUT_NOT_FOUND = 20005
    PAYOUT_COMMITTED = 20006
    PAYOUT_ROLLED_BACK = 20007
    DUPLICATE_CLIENT_ORDER_ID = 20008
    ADDRESS_GENERATION_ERROR = 20010
    WITHDRAWAL_NOT_FOUND = 20011
    WITHDRAWALS_DISABLED = 20012
    WITHDRAWAL_BELOW_MINIMUM = 20013
    WITHDRAWAL_ADDRESS_INVALID = 20014
    PAYMENT_ID_REQUIRED = 20015
    INVALID_CONFIRMATION_CODE = 20016
    WITHDRAW_ALREADY_CONFIRMED = 20017


class ApiErrorDetail(BaseModel):
    """API error detail structure."""

    model_config = ConfigDict(extra="allow")

    code: int
    message: str
    description: str | None = None


class ApiErrorResponse(BaseModel):
    """API error response wrapper."""

    model_config = ConfigDict(extra="allow")

    error: ApiErrorDetail
