from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class TransactionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PENDING = "PENDING"              # Out-of-order: waiting for previous sequence
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    RETRY_PENDING = "RETRY_PENDING"
    FAILED = "FAILED"


class TransactionType(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    REVERSAL = "REVERSAL"


class TransactionRequest(BaseModel):
    transactionId: str = Field(..., description="Unique business transaction ID")
    requestId: str = Field(..., description="Unique request/idempotency ID")
    accountId: str = Field(..., description="Target account/customer reference")
    transactionType: TransactionType
    amount: float
    currency: str = Field(default="USD", min_length=3, max_length=3)
    sequenceNumber: int = Field(..., description="Sequence number for account-level chronological ordering")
    simulateTransientError: bool = Field(default=False, description="Flag for resilience testing")

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Amount must be strictly positive (> 0), got: {v}")
        return round(v, 4)

    @field_validator("sequenceNumber")
    @classmethod
    def validate_sequence(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"sequenceNumber must be >= 1, got: {v}")
        return v


class TransactionRecord(BaseModel):
    transactionId: str
    requestId: str
    accountId: str
    transactionType: TransactionType
    amount: float
    currency: str
    sequenceNumber: int
    status: TransactionStatus = TransactionStatus.RECEIVED
    retryCount: int = 0
    maxRetries: int = 3
    failureReason: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)


class AccountRecord(BaseModel):
    accountId: str
    currency: str = "USD"
    currentBalance: float = 0.0
    lastProcessedSequence: int = 0
    updatedAt: datetime = Field(default_factory=datetime.utcnow)


class ProcessingSummary(BaseModel):
    totalReceived: int = 0
    processedCount: int = 0
    duplicateCount: int = 0
    failedCount: int = 0
    pendingCount: int = 0
    retryPendingCount: int = 0
    accounts: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    transactionAudit: List[Dict[str, Any]] = Field(default_factory=list)

