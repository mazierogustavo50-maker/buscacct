from django.db import models


class ExecucaoScraper(models.Model):
    STATUS_EM_ANDAMENTO = "EM_ANDAMENTO"
    STATUS_CONCLUIDO = "CONCLUIDO"
    STATUS_ERRO = "ERRO"
    STATUS_ABORTADO = "ABORTADO"
    STATUS_CHOICES = [
        (STATUS_EM_ANDAMENTO, "Em andamento"),
        (STATUS_CONCLUIDO, "Concluído"),
        (STATUS_ERRO, "Erro"),
        (STATUS_ABORTADO, "Abortado"),
    ]

    data_inicio = models.DateTimeField(auto_now_add=True)
    data_fim = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_EM_ANDAMENTO)
    total_baixados = models.IntegerField(default=0)
    total_ja_existentes = models.IntegerField(default=0)
    total_nao_encontrados = models.IntegerField(default=0)
    log_texto = models.TextField(blank=True)
    pid = models.IntegerField(null=True, blank=True)
    abortar = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Execução do Scraper"
        verbose_name_plural = "Execuções do Scraper"
        ordering = ["-data_inicio"]

    def __str__(self):
        return f"Execução {self.id} - {self.get_status_display()} ({self.data_inicio:%d/%m/%Y %H:%M})"
