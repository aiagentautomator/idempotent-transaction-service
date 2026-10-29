from typing import Tuple, Optional, Dict, Any
from src.models import TransactionRequest
from pydantic import ValidationError


class TransactionValidator:
    """Validates schema, mandatory fields, and business integrity (L2-FR-02)."""

    @staticmethod
    def validate_raw(payload: Dict[str, Any]) -> Tuple[Optional[TransactionRequest], Optional[str]]:
        """
        Validates a raw dictionary against the TransactionRequest contract.
        Returns (TransactionRequest, None) if valid, or (None, error_message) if invalid.
        """
        try:
            req = TransactionRequest(**payload)
            return req, None
        except ValidationError as e:
            # Extract readable error messages
            err_details = "; ".join([f"{err['loc'][0]}: {err['msg']}" for err in e.errors()])
            return None, f"Schema validation error: {err_details}"
        except Exception as ex:
            return None, f"Malformed record: {str(ex)}"

