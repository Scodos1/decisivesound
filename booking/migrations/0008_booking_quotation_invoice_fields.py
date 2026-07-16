# Generated for the Quotation & Invoice Management feature.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0007_equipmentinventory'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='quotation_number',
            field=models.CharField(blank=True, max_length=30, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='quotation_generated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='quotation_expiry_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='quotation_status',
            field=models.CharField(
                choices=[
                    ('Not Generated', 'Not Generated'),
                    ('Generated', 'Generated'),
                    ('Sent', 'Sent'),
                    ('Expired', 'Expired'),
                ],
                default='Not Generated',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='invoice_number',
            field=models.CharField(blank=True, max_length=30, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='invoice_generated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='invoice_status',
            field=models.CharField(
                choices=[
                    ('Not Generated', 'Not Generated'),
                    ('Generated', 'Generated'),
                    ('Sent', 'Sent'),
                ],
                default='Not Generated',
                max_length=20,
            ),
        ),
    ]
