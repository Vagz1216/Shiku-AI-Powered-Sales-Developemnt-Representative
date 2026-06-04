# Database Migrations

This project still keeps `db/schema.sql` and `db/schema_pg.sql` as full bootstrap schemas.
New database changes should be added here as versioned migration files before changing the bootstrap schemas.

Use this naming pattern:

```text
001_initial_schema.md
002_add_draft_approval_metadata.sql
003_add_rate_limit_table.sql
```

For now, no schema change was required for draft approval artifacts because approvals are recorded in the existing `events` table.
Before production, add a migration runner or Alembic and apply every migration to both local SQLite and Aurora/PostgreSQL.
