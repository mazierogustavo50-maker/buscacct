from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cctcore", "0007_documentocct_identificador_origem")]

    operations = [
        migrations.AddField(
            model_name="documentocct",
            name="reajuste_percentual_manual",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                max_digits=7,
                null=True,
                verbose_name="Atualização salarial manual (%)",
            ),
        ),
        migrations.AddField(
            model_name="documentocct",
            name="contribuicao_sindical_dominio",
            field=models.CharField(
                blank=True,
                choices=[("EMPREGADO", "Empregado"), ("PATRONAL", "Patronal"), ("AMBOS", "Ambos")],
                default="",
                max_length=20,
                verbose_name="Domínio da contribuição sindical",
            ),
        ),
        migrations.AddField(
            model_name="documentocct",
            name="contribuicao_sindical_valor_manual",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                verbose_name="Valor manual da contribuição sindical",
            ),
        ),
        migrations.AddField(
            model_name="documentocct",
            name="orientacoes_horas_extras",
            field=models.TextField(blank=True, default="", verbose_name="Orientações de horas extras"),
        ),
    ]
