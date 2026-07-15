import os
import time
import signal
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from cctbuscador.models import AgendamentoScraper, ExecucaoScraper
from cctbuscador.utils import iniciar_scraper_background


# Flag global para sinal de término
_sinal_terminar = False


def _handler_term(signum, frame):
    global _sinal_terminar
    _sinal_terminar = True


class Command(BaseCommand):
    help = "Verifica agendamentos do scraper e executa quando necessário."

    def add_arguments(self, parser):
        parser.add_argument(
            "--intervalo",
            type=int,
            default=60,
            help="Intervalo em segundos entre verificações (padrão: 60).",
        )

    def log(self, msg):
        self.stdout.write(msg)

    def calcular_proxima_execucao(self, ag):
        """Calcula a próxima execução com base na recorrência."""
        agora = timezone.now()
        base = ag.ultima_execucao or agora

        if ag.recorrencia == AgendamentoScraper.RECORRENCIA_DIARIA:
            prox = base + timedelta(days=1)
        elif ag.recorrencia == AgendamentoScraper.RECORRENCIA_SEMANAL:
            dias_ate = (ag.dia_semana - base.weekday()) % 7
            if dias_ate == 0 and base.time() >= ag.horario:
                dias_ate = 7
            prox = base + timedelta(days=dias_ate)
        elif ag.recorrencia == AgendamentoScraper.RECORRENCIA_MENSAL:
            try:
                prox = base.replace(day=ag.dia_mes)
                if prox <= base:
                    # Passa para o próximo mês
                    if prox.month == 12:
                        prox = prox.replace(year=prox.year + 1, month=1)
                    else:
                        prox = prox.replace(month=prox.month + 1)
            except ValueError:
                # Dia inválido para o mês (ex: 31/02)
                prox = base + timedelta(days=31)
        else:
            prox = base + timedelta(days=1)

        # Combina a data calculada com o horário do agendamento
        prox = prox.replace(hour=ag.horario.hour, minute=ag.horario.minute, second=0, microsecond=0)
        return prox

    def handle(self, *args, **options):
        global _sinal_terminar
        signal.signal(signal.SIGTERM, _handler_term)
        signal.signal(signal.SIGINT, _handler_term)

        intervalo = options["intervalo"]
        self.log("Verificador de agendamentos iniciado.")
        self.log(f"Intervalo de verificação: {intervalo}s")

        while not _sinal_terminar:
            agora = timezone.now()
            agendamentos = AgendamentoScraper.objects.filter(ativo=True)
            executados = 0

            for ag in agendamentos:
                if _sinal_terminar:
                    break

                proxima = ag.proxima_execucao
                if proxima is None:
                    # Primeira execução: verifica se já passou do horário de hoje
                    hoje_exec = agora.replace(hour=ag.horario.hour, minute=ag.horario.minute, second=0, microsecond=0)
                    if agora >= hoje_exec:
                        proxima = hoje_exec
                    else:
                        continue

                if agora >= proxima:
                    self.log(f"[AGENDAMENTO] Executando agendamento #{ag.id} ({ag})...")
                    try:
                        execucao = ExecucaoScraper.objects.create(
                            status=ExecucaoScraper.STATUS_EM_ANDAMENTO,
                        )
                        proc, log_path = iniciar_scraper_background(
                            execucao,
                            headless=ag.headless,
                            forcar=ag.forcar,
                            sindicato_codigo=ag.sindicato_codigo or "",
                        )
                        self.log(f"[AGENDAMENTO] Scraper iniciado (PID {proc.pid}, execução #{execucao.id}).")
                        executados += 1
                    except Exception as e:
                        self.log(f"[ERRO] Falha ao iniciar agendamento #{ag.id}: {e}")

                    # Atualiza última e próxima execução
                    ag.ultima_execucao = agora
                    ag.proxima_execucao = self.calcular_proxima_execucao(ag)
                    ag.save(update_fields=["ultima_execucao", "proxima_execucao"])
                    self.log(f"[AGENDAMENTO] Próxima execução: {ag.proxima_execucao}")

            if executados:
                self.log(f"{executados} agendamento(s) executado(s) neste ciclo.")

            # Aguarda até o próximo ciclo, verificando sinal a cada 1s
            for _ in range(intervalo):
                if _sinal_terminar:
                    break
                time.sleep(1)

        self.log("Verificador de agendamentos encerrado.")
