from sqlalchemy import Column, String, Boolean, Text
from app.core.database import Base


class User(Base):
    __tablename__ = "user_accounts"

    user_id         = Column(String, primary_key=True)
    email           = Column(String, unique=True, nullable=False)
    password_hash   = Column(String, nullable=False)
    name            = Column(String)
    phone           = Column(String)
    profile_picture = Column(String)
    bio             = Column(Text)
    city            = Column(String)
    state           = Column(String)
    zip_code        = Column(String)
    is_active       = Column(Boolean, default=True)
    is_verified     = Column(Boolean, default=False)
