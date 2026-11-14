from django.db import migrations, models
from django.utils import timezone


def start_existing_active_clocks(apps, schema_editor):
    Match = apps.get_model('gameplay', 'Match')
    Match.objects.filter(status='active').update(clock_started_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ('gameplay', '0002_match_black_guest_name_match_white_guest_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='match',
            name='white_time_ms',
            field=models.PositiveIntegerField(default=600000),
        ),
        migrations.AddField(
            model_name='match',
            name='black_time_ms',
            field=models.PositiveIntegerField(default=600000),
        ),
        migrations.AddField(
            model_name='match',
            name='clock_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(start_existing_active_clocks, migrations.RunPython.noop),
    ]
