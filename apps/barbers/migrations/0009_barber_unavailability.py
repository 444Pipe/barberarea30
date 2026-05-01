from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('barbers', '0008_barber_display_order'),
    ]

    operations = [
        migrations.CreateModel(
            name='BarberUnavailability',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(help_text='Fecha del bloqueo')),
                ('start_time', models.TimeField(help_text='Hora de inicio del bloqueo')),
                ('end_time', models.TimeField(help_text='Hora de fin del bloqueo')),
                ('reason', models.CharField(blank=True, help_text='Motivo opcional (emergencia, cita médica, etc.)', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('barber', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='unavailabilities',
                    to='barbers.barber',
                )),
            ],
            options={
                'verbose_name': 'Inactividad Temporal',
                'verbose_name_plural': 'Inactividades Temporales',
                'ordering': ['date', 'start_time'],
            },
        ),
    ]
