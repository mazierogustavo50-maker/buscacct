import os
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from cctcore.models import DocumentoCCT


class Command(BaseCommand):
    help = "Corrige documentos PENDENTES que j\u00e1 possuem PDF no disco para EXTRAIDO"

    def handle(self, *args, **options):
        base_dir = Path(settings.BASE_DIR)
        pendentes = DocumentoCCT.objects.filter(status_extracao=DocumentoCCT.STATUS_PENDENTE)
        corrigidos = 0
        sem_arquivo = 0

        for doc in pendentes:
            caminho = doc.arquivo_pdf
            if not caminho:
                sem_arquivo += 1
                continue

            # Resolve caminho absoluto
            if os.path.isabs(caminho):
                caminho_abs = Path(caminho)
            else:
                caminho_abs = base_dir / caminho

            if caminho_abs.exists() and caminho_abs.is_file():
                doc.status_extracao = DocumentoCCT.STATUS_EXTRAIDO
                # Garante que o caminho seja relativo ao BASE_DIR
                try:
                    caminho_relativo = str(caminho_abs.relative_to(base_dir))
                    if caminho_relativo != doc.arquivo_pdf:
                        doc.arquivo_pdf = caminho_relativo
                except ValueError:
                    pass
                doc.save(update_fields=["status_extracao", "arquivo_pdf"])
                corrigidos += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  Corrigido: {doc} -> EXTRAIDO")
                )
            else:
                sem_arquivo += 1
                self.stdout.write(
                    self.style.WARNING(f"  Arquivo n\u00e3o encontrado: {caminho_abs}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nResumo: {corrigidos} corrigido(s) | {sem_arquivo} sem arquivo no disco"
            )
        )
