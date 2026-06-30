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

    # Campos para análise com IA
    STATUS_ANALISE_PENDENTE = "PENDENTE"
    STATUS_ANALISE_EM_ANDAMENTO = "EM_ANDAMENTO"
    STATUS_ANALISE_CONCLUIDO = "CONCLUIDO"
    STATUS_ANALISE_ERRO = "ERRO"
    STATUS_ANALISE_CHOICES = [
        (STATUS_ANALISE_PENDENTE, "Pendente"),
        (STATUS_ANALISE_EM_ANDAMENTO, "Em andamento"),
        (STATUS_ANALISE_CONCLUIDO, "Concluído"),
        (STATUS_ANALISE_ERRO, "Erro"),
    ]

    status_analise_ia = models.CharField(
        max_length=20, choices=STATUS_ANALISE_CHOICES, default=STATUS_ANALISE_PENDENTE, blank=True
    )
    analise_ia_json = models.JSONField(null=True, blank=True)
    analise_ia_texto = models.TextField(blank=True)
    data_analise_ia = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Documento CCT"
        verbose_name_plural = "Documentos CCT"
        ordering = ["-data_inicio_vigencia", "sindicato", "tipo"]

    def __str__(self):
        return f"{self.tipo} - {self.sindicato} ({self.data_inicio_vigencia or 'sem data'})"


class ConfiguracaoSistema(models.Model):
    """Configurações globais do sistema (singleton)."""

    chave_api_opencode = models.CharField(
        max_length=255, blank=True, verbose_name="Chave API OpenCode Go"
    )
    modelo_padrao_opencode = models.CharField(
        max_length=50, default="kimi-k2.6", verbose_name="Modelo padrão OpenCode Go"
    )

    class Meta:
        verbose_name = "Configuração do Sistema"
        verbose_name_plural = "Configurações do Sistema"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_config(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Configuração do Sistema"
