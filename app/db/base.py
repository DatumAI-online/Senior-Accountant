"""Shared SQLAlchemy declarative base. Every model imports Base from here
so a single metadata object drives Alembic autogeneration."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
