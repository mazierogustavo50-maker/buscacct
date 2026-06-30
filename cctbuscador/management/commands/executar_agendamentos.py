import os
import sys
import subprocess
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from cctbuscador.models import AgendamentoScraper, ExecucaoScraper


class Command(BaseCommand):
    help = "Verifica e executa agendamentos do scraper que estejam programados para agora."

    def handle(self, *args, **options):
        agora = timezone.now()
        hoje = agora.date()
        hora_atual = agora.time()

        # Busca agendamentos ativos que ainda não executaram hoje
        agendamentos = AgendamentoScraper.objects.filter(ativo=True)
        executados = 0

        for ag in agendamentos:
            # Verifica se o horário já passou hoje
            if ag.horario > hora_atual:
                continue

            # Verifica se já executou hoje
            if ag.ultima_execucao and ag.ultima_execucao.date() == hoje:
                continue

            # Verifica recorrência
            deve_executar = False
            if ag.recorrencia == AgendamentoScraper.RECORRENCIA_DIARIA:
                deve_executar = True
            elif ag.recorrencia == AgendamentoScraper.RECORRENCIA_SEMANAL:
                if ag.dia_semana is not None and agora.weekday() == ag.dia_semana:
                    deve_executar = True
            elif ag.recorrencia == AgendamentoScraper.RECORRENCIA_MENSAL:
                if ag.dia_mes is not None and agora.day == ag.dia_mes:
                    deve_executar = True

            if not deve_executar:
                continue

            self.stdout.write(f"[AGENDAMENTO #{ag.pk}] Executando às {hora_atual.strftime('%H:%M')}...")

            # Inicia execução do scraper (mesma lógica da view web)
            manage_py = os.path.join(settings.BASE_DIR, "manage.py")
            cmd = [sys.executable, manage_py, "run_scraper"]
            if ag.headless:
                cmd.append("--headless")
            if ag.forcar:
                cmd.append("--forcar")
            if ag.sindicato_codigo:
                cmd.extend(["--sindicato-codigo", ag.sindicato_codigo])

            env = os.environ.copy()
            env.setdefault("DJANGO_SETTINGS_MODULE", "buscacct.settings")

            execucao = ExecucaoScraper.objects.create(
                status=ExecucaoScraper.STATUS_EM_ANDAMENTO,
            )
            cmd.extend(["--execucao-id", str(execucao.id)])

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    cwd=settings.BASE_DIR,
                    env=env,
                )
                execucao.pid = proc.pid
                execucao.save(update_fields=["pid"])
                self.stdout.write(f"  [OK] Scraper iniciado (PID {proc.pid}, Execução #{execucao.id})")

                # Atualiza agendamento
                ag.ultima_execucao = agora
                ag.save(update_fields=["ultima_execucao"])
                executados += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  [ERRO] Falha ao iniciar scraper: {e}"))
                execucao.status = ExecucaoScraper.STATUS_ERRO
                execucao.save(update_fields=["status"])

        if executados == 0:
            self.stdout.write("Nenhum agendamento para executar agora.")
        else:
            self.stdout.write(self.style.SUCCESS(f"{executados} agendamento(s) iniciado(s)."))
