"""
Comando utilitário para forçar o abortamento de execuções do scraper.
Útil quando a interface web não consegue abortar (processo zumbi, PID inválido, etc.)
"""
import os
import signal
import sys

from django.core.management.base import BaseCommand
from cctbuscador.models import ExecucaoScraper


class Command(BaseCommand):
    help = "Força o abortamento de execuções do scraper por ID."

    def add_arguments(self, parser):
        parser.add_argument(
            "ids",
            nargs="+",
            type=int,
            help="IDs das execuções a serem abortadas.",
        )
        parser.add_argument(
            "--matar",
            action="store_true",
            help="Tenta enviar SIGTERM/SIGKILL para o PID, se houver.",
        )
        parser.add_argument(
            "--limpar",
            action="store_true",
            help="Apaga os registros informados após abortar.",
        )

    def handle(self, *args, **options):
        ids = options["ids"]
        matar = options["matar"]
        limpar = options["limpar"]

        abortadas = 0
        apagadas = 0
        erros = 0

        for pk in ids:
            try:
                execucao = ExecucaoScraper.objects.get(pk=pk)
            except ExecucaoScraper.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"[ERRO] Execução #{pk} não encontrada."))
                erros += 1
                continue

            # Se ainda está em andamento, marca como abortado
            if execucao.status == ExecucaoScraper.STATUS_EM_ANDAMENTO:
                execucao.status = ExecucaoScraper.STATUS_ABORTADO
                if not execucao.data_fim:
                    from django.utils import timezone
                    execucao.data_fim = timezone.now()
                execucao.save(update_fields=["status", "data_fim"])
                self.stdout.write(self.style.WARNING(f"[ABORTADO] Execução #{pk} marcada como abortada."))
            else:
                self.stdout.write(self.style.NOTICE(f"[INFO] Execução #{pk} já estava '{execucao.status}'."))

            # Tenta matar o processo se solicitado
            if matar and execucao.pid:
                try:
                    os.kill(execucao.pid, signal.SIGTERM)
                    self.stdout.write(self.style.WARNING(f"  → SIGTERM enviado para PID {execucao.pid}."))
                except ProcessLookupError:
                    self.stdout.write(self.style.NOTICE(f"  → PID {execucao.pid} já não existe."))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  → Erro ao matar PID {execucao.pid}: {e}"))

                # Tenta matar filhos via psutil
                try:
                    import psutil
                    parent = psutil.Process(execucao.pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    gone, alive = psutil.wait_procs(children, timeout=3)
                    for p in alive:
                        try:
                            p.kill()
                        except psutil.NoSuchProcess:
                            pass
                    self.stdout.write(self.style.WARNING(f"  → {len(children)} filho(s) finalizado(s)."))
                except psutil.NoSuchProcess:
                    self.stdout.write(self.style.NOTICE(f"  → Processo {execucao.pid} já encerrado."))
                except ImportError:
                    self.stdout.write(self.style.NOTICE("  → psutil não instalado (pip install psutil)."))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  → Erro ao matar filhos: {e}"))

            # Limpa registro se solicitado
            if limpar:
                execucao.delete()
                self.stdout.write(self.style.SUCCESS(f"[APAGADO] Execução #{pk} removida do banco."))
                apagadas += 1
            else:
                abortadas += 1

        self.stdout.write("\n" + "=" * 50)
        if limpar:
            self.stdout.write(self.style.SUCCESS(f"Resumo: {apagadas} apagada(s), {erros} erro(s)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Resumo: {abortadas} abortada(s), {erros} erro(s)."))
