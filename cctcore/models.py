from django.db import models


class Sindicato(models.Model):
    codigo = models.CharField(max_length=20, unique=True, db_index=True)
    cnpj = models.CharField(max_length=14, blank=True, db_index=True)
    nome = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Sindicato"
        verbose_name_plural = "Sindicatos"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.nome}"


class Empresa(models.Model):
    codigo = models.CharField(max_length=20, db_index=True)
    nome = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.codigo} - {self.nome}"


class EmpresaSindicato(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="sindicatos")
    sindicato = models.ForeignKey(Sindicato, on_delete=models.CASCADE, related_name="empresas")

    class Meta:
        verbose_name = "Relação Empresa-Sindicato"
        verbose_name_plural = "Relações Empresa-Sindicato"
        unique_together = [["empresa", "sindicato"]]

    def __str__(self):
        return f"{self.empresa} <> {self.sindicato}"


class DocumentoCCT(models.Model):
    TIPO_CCT = "CCT"
    TIPO_TA_CCT = "TA-CCT"
    TIPO_CHOICES = [
        (TIPO_CCT, "CCT"),
        (TIPO_TA_CCT, "TA-CCT"),
    ]

    STATUS_PENDENTE = "PENDENTE"
    STATUS_EXTRAIDO = "EXTRAIDO"
    STATUS_ERRO = "ERRO"
    STATUS_CHOICES = [
        (STATUS_PENDENTE, "Pendente"),
        (STATUS_EXTRAIDO, "Extraído"),
        (STATUS_ERRO, "Erro"),
    ]

    sindicato = models.ForeignKey(
        Sindicato, on_delete=models.CASCADE, related_name="documentos"
    )
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    data_inicio_vigencia = models.DateField(null=True, blank=True)
    data_fim_vigencia = models.DateField(null=True, blank=True)
    arquivo_pdf = models.CharField(max_length=500, blank=True)
    data_base = models.DateField(null=True, blank=True)
    reajuste_percentual = models.DecimalField(
        max_digits=7, decimal_places=4, null=True, blank=True
    )
    contribuicao_sindical_empregado = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    contribuicao_sindical_patronal = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    status_extracao = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDENTE
    )
    ativo = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Documento CCT"
        verbose_name_plural = "Documentos CCT"
        ordering = ["-data_inicio_vigencia", "sindicato", "tipo"]

    def __str__(self):
        return f"{self.tipo} - {self.sindicato} ({self.data_inicio_vigencia or 'sem data'})"
