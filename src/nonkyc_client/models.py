"""Shared data models for NonKYC clients.

Pydantic-based models with validation, maintaining backward compatibility.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TradingPair(BaseModel):
    """Trading pair model."""

    model_config = ConfigDict(frozen=True)

    base: str
    quote: str

    @property
    def symbol(self) -> str:
        """Return formatted symbol."""
        return f"{self.base}/{self.quote}"


class Balance(BaseModel):
    """Account balance model with validation."""

    model_config = ConfigDict(frozen=True)

    asset: str
    available: str
    held: str
    pending: str = "0"  # Added field from API spec

    @field_validator("available", "held", "pending", mode="before")
    @classmethod
    def validate_balance_amounts(cls, v: Any) -> str:
        """Validate balance amounts are valid non-negative decimals."""
        if v is None:
            return "0"
        try:
            decimal_val = Decimal(str(v))
            if decimal_val < 0:
                raise ValueError("Balance cannot be negative")
            return str(v)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid balance amount: {v}") from e


class OrderRequest(BaseModel):
    """Order creation request model."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    side: str
    order_type: str
    quantity: str
    price: str | None = None
    user_provided_id: str | None = None
    strict_validate: bool | None = None

    @field_validator("quantity", "price", mode="before")
    @classmethod
    def validate_amounts(cls, v: Any) -> str | None:
        """Validate amounts are valid positive decimals."""
        if v is None:
            return None
        try:
            decimal_val = Decimal(str(v))
            if decimal_val <= 0:
                raise ValueError("Amount must be positive")
            return str(v)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid amount: {v}") from e

    def to_payload(self) -> dict[str, Any]:
        """Convert to API request payload."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "side": self.side,
            "type": self.order_type,
            "quantity": self.quantity,
        }
        if self.price is not None:
            payload["price"] = self.price
        if self.user_provided_id is not None:
            payload["userProvidedId"] = self.user_provided_id
        if self.strict_validate is not None:
            payload["strictValidate"] = self.strict_validate
        return payload


class OrderResponse(BaseModel):
    """Order creation response model."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    order_id: str
    symbol: str
    status: str
    raw_payload: Mapping[str, Any] = Field(default_factory=dict)


class OrderStatus(BaseModel):
    """Order status model."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    order_id: str
    symbol: str
    status: str
    filled_quantity: str | None = None
    remaining_quantity: str | None = None
    raw_payload: Mapping[str, Any] = Field(default_factory=dict)


class OrderCancelResult(BaseModel):
    """Order cancellation result model."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    order_id: str
    success: bool
    raw_payload: Mapping[str, Any] = Field(default_factory=dict)


class MarketTicker(BaseModel):
    """Market ticker data model."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    symbol: str
    last_price: str | None = None  # Allow None or empty string
    bid: str | None = None
    ask: str | None = None
    volume: str | None = None
    raw_payload: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("last_price", "bid", "ask", "volume", mode="before")
    @classmethod
    def validate_price_fields(cls, v: Any) -> str | None:
        """Validate price fields are valid decimals."""
        if v is None or v == "":
            return None
        try:
            Decimal(str(v))
            return str(v)
        except (ValueError, TypeError):
            # Allow invalid values to pass through for backward compatibility
            return str(v)


class OrderBookLevel(BaseModel):
    """Order book price level model."""

    model_config = ConfigDict(frozen=True)

    price: str
    quantity: str

    @field_validator("price", "quantity", mode="before")
    @classmethod
    def validate_amounts(cls, v: Any) -> str:
        """Validate amounts are valid decimals."""
        try:
            Decimal(str(v))
            return str(v)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid amount: {v}") from e


class OrderBookSnapshot(BaseModel):
    """Order book snapshot model."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    symbol: str
    bids: Sequence[OrderBookLevel]
    asks: Sequence[OrderBookLevel]
    timestamp: float | None = None
    raw_payload: Mapping[str, Any] = Field(default_factory=dict)


class Trade(BaseModel):
    """Trade execution model."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    trade_id: str
    symbol: str
    price: str
    quantity: str
    side: str | None = None
    timestamp: float | None = None
    raw_payload: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("price", "quantity", mode="before")
    @classmethod
    def validate_amounts(cls, v: Any) -> str:
        """Validate amounts are valid decimals."""
        try:
            Decimal(str(v))
            return str(v)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid amount: {v}") from e
