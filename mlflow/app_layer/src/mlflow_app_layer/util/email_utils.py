from typing import Union
from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError


def validate_email(email: Union[str, None]) -> str:
    """
    Validate email format and raise HTTPException if invalid.
    
    Args:
        email: Email string to validate
        
    Returns:
        The validated email string
        
    Raises:
        HTTPException: If email is None or has invalid format
    """
    if email is None:
        raise HTTPException(status_code=401, detail="Email header is required")
    
    try:
        # Use Pydantic's TypeAdapter for email validation
        # This uses the email-validator library under the hood for RFC 5322 compliance
        from pydantic import EmailStr
        adapter = TypeAdapter(EmailStr)
        adapter.validate_python(email)
        return email
    except (ValidationError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail="Invalid email format"
        ) from e

