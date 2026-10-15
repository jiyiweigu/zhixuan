"""Use JSON vectors on SQLite and native pgvector on PostgreSQL."""
from alembic import op
import sqlalchemy as sa
revision = "0010_embedding_vector"
down_revision = "0009_school_major_score_identity"
branch_labels = None
depends_on = None
def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql": return
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.execute(sa.text("ALTER TABLE knowledge_chunk ALTER COLUMN embedding TYPE vector(512) USING CASE WHEN embedding IS NULL OR embedding::text = 'null' THEN NULL ELSE embedding::text::vector(512) END"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_knowledge_chunk_embedding_hnsw ON knowledge_chunk USING hnsw (embedding vector_cosine_ops)"))
def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql": return
    op.execute(sa.text("DROP INDEX IF EXISTS ix_knowledge_chunk_embedding_hnsw"))
    op.execute(sa.text("ALTER TABLE knowledge_chunk ALTER COLUMN embedding TYPE json USING CASE WHEN embedding IS NULL THEN NULL ELSE embedding::text::json END"))
