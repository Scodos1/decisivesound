# Generated to set headset inventory to 10,000 as requested
from django.db import migrations


def set_headset_inventory(apps, schema_editor):
    EquipmentInventory = apps.get_model("booking", "EquipmentInventory")
    obj, created = EquipmentInventory.objects.get_or_create(
        equipment_type="Headset",
        defaults={
            "name": "Silent Disco Headset",
            "total_quantity": 10000,
            "maintenance_quantity": 0,
        },
    )
    if not created and obj.total_quantity != 10000:
        obj.total_quantity = 10000
        obj.save(update_fields=["total_quantity"])


def reverse_headset_inventory(apps, schema_editor):
    # No reverse - leave as is
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0013_galleryimage_video_support'),
    ]

    operations = [
        migrations.RunPython(set_headset_inventory, reverse_headset_inventory),
    ]
