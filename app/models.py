from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    email = Column(String(150), unique=True, nullable=False)
    username = Column(String(50), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=True)
    full_name = Column(String(100), nullable=False)
    avatar_url = Column(String(255), nullable=True)
    role = Column(
        PgEnum("admin", "cashier", "manager", name="user_role", create_type=False),
        nullable=False,
        default="cashier",
    )
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UserOAuthAccount(Base):
    __tablename__ = "user_oauth_accounts"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(
        PgEnum("google", "discord", name="oauth_provider", create_type=False),
        nullable=False,
    )
    provider_user_id = Column(String(100), nullable=False)
    provider_email = Column(String(150), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)