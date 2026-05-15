from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDTimestampMixin


class Programme(UUIDTimestampMixin, Base):
    __tablename__ = "programmes"
    __table_args__ = (
        CheckConstraint(
            "ay_date_category IN ('im_subspec', 'non_im_subspec')",
            name="ck_programmes_ay_date_category",
        ),
        Index(
            "idx_programmes_rdb_alias",
            "rdb_alias",
            postgresql_where=text("rdb_alias IS NOT NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ay_date_category: Mapped[str] = mapped_column(String(30), nullable=False)
    r_year_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    is_subspecialty: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    rdb_alias: Mapped[str | None] = mapped_column(String(100), nullable=True)
