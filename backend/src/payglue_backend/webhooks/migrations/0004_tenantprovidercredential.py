# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('webhooks', '0003_integrationconfig_productmapping'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantProviderCredential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_slug', models.CharField(max_length=64)),
                ('provider_key', models.CharField(max_length=64)),
                ('credentials_enc', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(
                        fields=('tenant_slug', 'provider_key'),
                        name='webhooks_unique_credential_per_tenant_provider',
                    )
                ],
                'indexes': [
                    models.Index(fields=['tenant_slug', 'provider_key'], name='webhooks_te_tenant__cred_idx'),
                ],
            },
        ),
    ]
