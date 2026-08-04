import os
import sys
import subprocess
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from cctbuscador.models import AgendamentoScraper, ExecucaoScraper


class Command(BaseCommand):
    help = "Executa agendamentos vencidos no horário de São Paulo."
    tz = ZoneInfo("America/Sao_Paulo")

    def deve_executar(self, agendamento, agora):
        if agora.time() < agendamento.horario:
            return False
        if agendamento.ultima_execucao:
            ultima_local = timezone.localtime(agendamento.ultima_execucao, self.tz)
            if ultima_local.date() == agora.date():
                return False
        if agendamento.recorrencia == AgendamentoScraper.RECORRENCIA_SEMANAL:
            return agendamento.dia_semana == agora.weekday()
        if agendamento.recorrencia == AgendamentoScraper.RECORRENCIA_MENSAL:
            return agendamento.dia_mes == agora.day
        return agendamento.recorrencia == AgendamentoScraper.RECORRENCIA_DIARIA

    def iniciar_processo(self, agendamento, execucao):
        manage_py = os.path.join(settings.BASE_DIR, "manage.py")
        cmd = [sys.executable, manage_py, "run_scraper"]
        if agendamento.headless:
            cmd.append("--headless")
        if agendamento.forcar:
            cmd.append("--forcar")
        if agendamento.sindicato_codigo:
            cmd.extend(["--sindicato-codigo", agendamento.sindicato_codigo])
        cmd.extend(["--execucao-id", str(execucao.pk)])
        env = os.environ.copy()
        env["DJANGO_SETTINGS_MODULE"] = "buscacct.settings"
        env.setdefault("TZ", "America/Sao_Paulo")
        return subprocess.Popen(
            cmd, cwd=settings.BASE_DIR, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )

    def handle(self, *args, **options):
        agora = timezone.localtime(timezone.now(), self.tz)
        executados = 0
        for ag_base in AgendamentoScraper.objects.filter(ativo=True).order_by("pk"):
            with transaction.atomic():
                ag = AgendamentoScraper.objects.select_for_update().get(pk=ag_base.pk)
                if not ag.ativo or not self.deve_executar(ag, agora):
                    continue
                execucao = ExecucaoScraper.objects.create(status=ExecucaoScraper.STATUS_EM_ANDAMENTO)
                try:
                    proc = self.iniciar_processo(ag, execucao)
                except Exception as exc:
                    execucao.status = ExecucaoScraper.STATUS_ERRO
                    execucao.log_texto = str(exc)
                    execucao.data_fim = timezone.now()
                    execucao.save(update_fields=["status", "log_texto", "data_fim"])
                    self.stderr.write(f"[ERRO] Agendamento #{ag.pk}: {exc}")
                    continue
                execucao.pid = proc.pid
                execucao.save(update_fields=["pid"])
                ag.ultima_execucao = timezone.now()
                ag.save(update_fields=["ultima_execucao"])
                executados += 1
                self.stdout.write(self.style.SUCCESS(
                    f"[OK] Agendamento #{ag.pk} iniciado (execução #{execucao.pk}, PID {proc.pid})."
                ))
        if not executados:
            self.stdout.write("Nenhum agendamento para executar agora.")
        else:
            self.stdout.write(self.style.SUCCESS(f"{executados} agendamento(s) iniciado(s)."))
