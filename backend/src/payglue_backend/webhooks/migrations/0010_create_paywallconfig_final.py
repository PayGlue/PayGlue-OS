# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


CREATE_SQL = """
DO $$
BEGIN
    CREATE TABLE IF NOT EXISTS "webhooks_paywallconfig" (
        "id" varchar(32) NOT NULL PRIMARY KEY,
        "tenant_slug" varchar(64) NOT NULL,
        "name" varchar(255) NOT NULL,
        "product_id" varchar(255) NOT NULL DEFAULT '',
        "product_name" varchar(255) NOT NULL DEFAULT '',
        "headline" varchar(255) NOT NULL DEFAULT 'Premium content',
        "body" text NOT NULL DEFAULT 'Purchase access to continue reading.',
        "button_text" varchar(128) NOT NULL DEFAULT 'Get access',
        "button_url" varchar(512) NOT NULL DEFAULT '',
        "button_color" varchar(16) NOT NULL DEFAULT '#4f46e5',
        "created_at" timestamp with time zone NOT NULL,
        "updated_at" timestamp with time zone NOT NULL
    );
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'webhooks_pw_tenant__idx'
    ) THEN
        CREATE INDEX "webhooks_pw_tenant__idx"
            ON "webhooks_paywallconfig" ("tenant_slug", "created_at");
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_index i ON c.oid = i.indrelid
        JOIN pg_class c2 ON c2.oid = i.indexrelid
        WHERE c.relname = 'webhooks_paywallconfig' AND c2.relname LIKE 'webhooks_paywallconfig_tenant_slug%'
    ) THEN
        CREATE INDEX "webhooks_paywallconfig_tenant_slug_auto"
            ON "webhooks_paywallconfig" ("tenant_slug");
    END IF;
END $$;
"""

REVERSE_SQL = "DROP TABLE IF EXISTS webhooks_paywallconfig CASCADE;"


class Migration(migrations.Migration):

    dependencies = [
        ('webhooks', '0009_ensure_paywallconfig_table'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(CREATE_SQL, reverse_sql=REVERSE_SQL),
            ],
            state_operations=[
                migrations.CreateModel(
                    name='PaywallConfig',
                    fields=[
                        ('id', models.CharField(max_length=32, primary_key=True, serialize=False)),
                        ('tenant_slug', models.CharField(db_index=True, max_length=64)),
                        ('name', models.CharField(max_length=255)),
                        ('product_id', models.CharField(blank=True, default='', max_length=255)),
                        ('product_name', models.CharField(blank=True, default='', max_length=255)),
                        ('headline', models.CharField(default='Premium content', max_length=255)),
                        ('body', models.TextField(default='Purchase access to continue reading.')),
                        ('button_text', models.CharField(default='Get access', max_length=128)),
                        ('button_url', models.URLField(blank=True, default='', max_length=512)),
                        ('button_color', models.CharField(default='#4f46e5', max_length=16)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        'indexes': [
                            models.Index(fields=['tenant_slug', 'created_at'], name='webhooks_pw_tenant__idx'),
                        ],
                    },
                ),
            ],
        ),
    ]
