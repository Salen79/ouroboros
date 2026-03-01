from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
from app.database import get_db
from app.models.user import User
from app.auth import verify_password, hash_password, create_access_token, get_current_user
import uuid

router = APIRouter(prefix="/api/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""
    company_name: str = ""

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user = User(
        id=uuid.uuid4(),
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        company_name=req.company_name,
        plan="free",
        credits_remaining=3,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user={"id": str(user.id), "email": user.email, "plan": user.plan, "credits": user.credits_remaining}
    )

@router.post("/token", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user={"id": str(user.id), "email": user.email, "plan": user.plan, "credits": user.credits_remaining}
    )

@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "email": user.email, "plan": user.plan, "credits": user.credits_remaining, "full_name": user.full_name, "company_name": user.company_name}
