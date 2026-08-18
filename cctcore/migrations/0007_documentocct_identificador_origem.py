from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cctcore", "0006_documentocct_data_registro_mte_and_more")]

    operations = [
        migrations.AddField(
            model_name="documentocct",
            name="identificador_origem",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=64,
                null=True,
                unique=True,
                verbose_name="Identificador do documento na origem",
            ),
        ),
    ]
