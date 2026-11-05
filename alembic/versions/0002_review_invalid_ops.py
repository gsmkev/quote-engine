"""allow review reason invalid_ops"""

from alembic import op

revision = "0002"
down_revision = "0001"

REASONS = "'ambiguous_quote','ambiguous_line','extraction_failed','unknown_product'"


def _reason_check(reasons: str) -> None:
    op.execute("ALTER TABLE review_items DROP CONSTRAINT review_items_reason_check")
    op.execute(
        f"ALTER TABLE review_items ADD CONSTRAINT review_items_reason_check "
        f"CHECK (reason IN ({reasons}))"
    )


def upgrade() -> None:
    _reason_check(f"{REASONS},'invalid_ops'")


def downgrade() -> None:
    _reason_check(REASONS)
