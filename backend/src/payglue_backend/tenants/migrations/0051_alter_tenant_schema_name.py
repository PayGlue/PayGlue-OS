# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
# PG-273: records the field as it stands now that Tenant no longer inherits
# django_tenants' TenantMixin. The only difference is the dropped schema-name
# validator, which was Python-only, so this produces no column change.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0050_support_account_email'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenant',
            name='schema_name',
            field=models.CharField(db_index=True, max_length=63, unique=True),
        ),
    ]
