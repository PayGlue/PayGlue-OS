# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


CREATE_SQL = """
DO $$
BEGIN
    CREATE TABLE IF NOT EXISTS "webhooks_buybutton" (
        "id" varchar(32) NOT NULL PRIMARY KEY,
        "tenant_slug" varchar(64) NOT NULL,
        "name" varchar(255) NOT NULL,
        "label" varchar(128) NOT NULL DEFAULT 'Buy now',
        "description" text NOT NULL DEFAULT '',
        "target_url" varchar(512) NOT NULL DEFAULT '',
        "bg_color" varchar(16) NOT NULL DEFAULT '#4f46e5',
        "text_color" varchar(16) NOT NULL DEFAULT '#ffffff',
        "border_radius" varchar(8) NOT NULL DEFAULT 'md',
        "width" varchar(8) NOT NULL DEFAULT 'auto',
        "alignment" varchar(8) NOT NULL DEFAULT 'left',
        "created_at" timestamp with time zone NOT NULL,
        "updated_at" timestamp with time zone NOT NULL
    );
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'webhooks_bb_tenant__idx'
    ) THEN
        CREATE INDEX "webhooks_bb_tenant__idx"
            ON "webhooks_buybutton" ("tenant_slug", "created_at");
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'webhooks_buybutton_tenant_slug_auto'
    ) THEN
        CREATE INDEX "webhooks_buybutton_tenant_slug_auto"
            ON "webhooks_buybutton" ("tenant_slug");
    END IF;
END $$;
"""

REVERSE_SQL = "DROP TABLE IF EXISTS webhooks_buybutton CASCADE;"


class Migration(migrations.Migration):

    dependencies = [
        ('webhooks', '0010_create_paywallconfig_final'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(CREATE_SQL, reverse_sql=REVERSE_SQL),
            ],
            state_operations=[
                migrations.CreateModel(
                    name='BuyButton',
                    fields=[
                        ('id', models.CharField(max_length=32, primary_key=True, serialize=False)),
                        ('tenant_slug', models.CharField(db_index=True, max_length=64)),
                        ('name', models.CharField(max_length=255)),
                        ('label', models.CharField(default='Buy now', max_length=128)),
                        ('description', models.TextField(blank=True, default='')),
                        ('target_url', models.URLField(blank=True, default='', max_length=512)),
                        ('bg_color', models.CharField(default='#4f46e5', max_length=16)),
                        ('text_color', models.CharField(default='#ffffff', max_length=16)),
                        ('border_radius', models.CharField(choices=[('none', 'none'), ('md', 'md'), ('full', 'full')], default='md', max_length=8)),
                        ('width', models.CharField(choices=[('auto', 'auto'), ('full', 'full')], default='auto', max_length=8)),
                        ('alignment', models.CharField(choices=[('left', 'left'), ('center', 'center'), ('right', 'right')], default='left', max_length=8)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        'indexes': [
                            models.Index(fields=['tenant_slug', 'created_at'], name='webhooks_bb_tenant__idx'),
                        ],
                    },
                ),
            ],
        ),
    ]
