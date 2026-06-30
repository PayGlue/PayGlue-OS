# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models

ADD_COLUMNS_SQL = """
ALTER TABLE webhooks_paywallconfig
    ADD COLUMN IF NOT EXISTS text_color varchar(16) NOT NULL DEFAULT '#ffffff',
    ADD COLUMN IF NOT EXISTS border_radius varchar(8) NOT NULL DEFAULT 'md',
    ADD COLUMN IF NOT EXISTS width varchar(8) NOT NULL DEFAULT 'auto',
    ADD COLUMN IF NOT EXISTS alignment varchar(8) NOT NULL DEFAULT 'left';
"""

REVERSE_SQL = """
ALTER TABLE webhooks_paywallconfig
    DROP COLUMN IF EXISTS text_color,
    DROP COLUMN IF EXISTS border_radius,
    DROP COLUMN IF EXISTS width,
    DROP COLUMN IF EXISTS alignment;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('webhooks', '0011_create_buybutton'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(ADD_COLUMNS_SQL, reverse_sql=REVERSE_SQL),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='paywallconfig',
                    name='text_color',
                    field=models.CharField(default='#ffffff', max_length=16),
                ),
                migrations.AddField(
                    model_name='paywallconfig',
                    name='border_radius',
                    field=models.CharField(default='md', max_length=8),
                ),
                migrations.AddField(
                    model_name='paywallconfig',
                    name='width',
                    field=models.CharField(default='auto', max_length=8),
                ),
                migrations.AddField(
                    model_name='paywallconfig',
                    name='alignment',
                    field=models.CharField(default='left', max_length=8),
                ),
            ],
        ),
    ]
