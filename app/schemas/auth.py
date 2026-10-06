from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=10)
    confirm_password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class OtpVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
