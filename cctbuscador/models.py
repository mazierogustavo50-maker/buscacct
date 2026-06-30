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
    nao_encontrados_json = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Execução do Scraper"
        verbose_name_plural = "Execuções do Scraper"
        ordering = ["-data_inicio"]

    def __str__(self):
        return f"Execução {self.id} - {self.get_status_display()} ({self.data_inicio:%d/%m/%Y %H:%M})"


class AgendamentoScraper(models.Model):
    RECORRENCIA_DIARIA = "DIARIA"
    RECORRENCIA_SEMANAL = "SEMANAL"
    RECORRENCIA_MENSAL = "MENSAL"
    RECORRENCIA_CHOICES = [
        (RECORRENCIA_DIARIA, "Diária"),
        (RECORRENCIA_SEMANAL, "Semanal"),
        (RECORRENCIA_MENSAL, "Mensal"),
    ]

    DIAS_SEMANA = [
        (0, "Segunda"),
        (1, "Terça"),
        (2, "Quarta"),
        (3, "Quinta"),
        (4, "Sexta"),
        (5, "Sábado"),
        (6, "Domingo"),
    ]

    ativo = models.BooleanField(default=True, db_index=True)
    horario = models.TimeField(help_text="Horário de execução (HH:MM)")
    recorrencia = models.CharField(
        max_length=20, choices=RECORRENCIA_CHOICES, default=RECORRENCIA_DIARIA
    )
    dia_semana = models.IntegerField(
        choices=DIAS_SEMANA, null=True, blank=True,
        help_text="Obrigatório apenas para recorrência semanal"
    )
    dia_mes = models.IntegerField(
        null=True, blank=True,
        help_text="Obrigatório apenas para recorrência mensal (1-31)"
    )
    headless = models.BooleanField(default=True, verbose_name="Headless")
    sindicato_codigo = models.CharField(
        max_length=20, blank=True, verbose_name="Código do Sindicato",
        help_text="Deixe em branco para processar todos os sindicatos"
    )
    forcar = models.BooleanField(default=False, verbose_name="Forçar re-download")
    ultima_execucao = models.DateTimeField(null=True, blank=True)
    proxima_execucao = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Agendamento do Scraper"
        verbose_name_plural = "Agendamentos do Scraper"
        ordering = ["horario"]

    def __str__(self):
        rec = self.get_recorrencia_display()
        if self.recorrencia == self.RECORRENCIA_SEMANAL and self.dia_semana is not None:
            rec += f" ({self.get_dia_semana_display()})"
        elif self.recorrencia == self.RECORRENCIA_MENSAL and self.dia_mes:
            rec += f" (dia {self.dia_mes})"
        return f"{self.horario.strftime('%H:%M')} - {rec} {'(ativo)' if self.ativo else '(inativo)'}"
