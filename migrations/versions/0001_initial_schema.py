"""Initial schema: customers, products, invoices and their lines.

Revision ID: 0001
Revises:
Created: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

MONEY = sa.Numeric(12, 2)
UNIT_TAX_SQL = "round(unit_price_without_tax * vat_rate / 100, 2)"


def upgrade() -> None:
    # Trigram matching, for fast "contains" searches on names and labels.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "customers",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("first_name", sa.Text, nullable=False),
        sa.Column("last_name", sa.Text, nullable=False),
        sa.Column("address", sa.Text, nullable=False),
        sa.Column("zip_code", sa.String(10), nullable=False),
        sa.Column("city", sa.Text, nullable=False),
        sa.Column("country", sa.Text, nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
    )
    op.execute(
        "CREATE INDEX ix_customers_first_last_trgm ON customers "
        "USING gin ((first_name || ' ' || last_name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_customers_last_first_trgm ON customers "
        "USING gin ((last_name || ' ' || first_name) gin_trgm_ops)"
    )

    unit = sa.Enum("hour", "day", "piece", name="unit")
    op.create_table(
        "products",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("unit", unit, nullable=False),
        sa.Column("vat_rate", sa.Numeric(3, 1), nullable=False),
        sa.Column("unit_price_without_tax", MONEY, nullable=False),
        sa.Column("unit_tax", MONEY, sa.Computed(UNIT_TAX_SQL, persisted=True), nullable=False),
        sa.Column(
            "unit_price",
            MONEY,
            sa.Computed(f"unit_price_without_tax + {UNIT_TAX_SQL}", persisted=True),
            nullable=False,
        ),
        sa.CheckConstraint("vat_rate IN (0, 5.5, 10, 20)", name="ck_products_vat_rate"),
        sa.CheckConstraint("unit_price_without_tax >= 0", name="ck_products_price_positive"),
    )
    op.create_index(
        "ix_products_label_trgm",
        "products",
        ["label"],
        postgresql_using="gin",
        postgresql_ops={"label": "gin_trgm_ops"},
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column(
            "customer_id",
            sa.Integer,
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("finalized", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("paid", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("date", sa.Date, nullable=True),
        sa.Column("deadline", sa.Date, nullable=True),
        sa.CheckConstraint("finalized OR NOT paid", name="ck_invoices_paid_needs_finalized"),
    )
    op.create_index("ix_invoices_customer_id", "invoices", ["customer_id"])
    op.create_index("ix_invoices_deadline", "invoices", ["deadline"])

    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.Integer,
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer,
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_invoice_lines_quantity_positive"),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])
    op.create_index("ix_invoice_lines_product_id", "invoice_lines", ["product_id"])


def downgrade() -> None:
    op.drop_table("invoice_lines")
    op.drop_table("invoices")
    op.drop_table("products")
    op.drop_table("customers")
    sa.Enum(name="unit").drop(op.get_bind(), checkfirst=True)
    # pg_trgm stays: other schemas in the same database may use it.
