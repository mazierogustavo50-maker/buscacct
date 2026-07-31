import os
import time
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import connection
from pathlib import Path

from cctcore.models import DocumentoCCT
from cctcore.services import extrair_texto_pdf
try:
    from cctcore.services import analisar_cct_com_ia
except ImportError:
    analisar_cct_com_ia = None
from cctcore.management.commands.atualizar_vigencias import extrair_datas_do_texto, extrair_dados_complementares_do_texto


def _parse_data_br(valor):
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date() if hasattr(valor, 'date') else None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(str(valor).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(valor):
    if valor is None:
        return None
    from decimal import Decimal, InvalidOperation
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))
    s = str(valor).strip()
    if not s or s.lower() in ("null", "none", "-", "n/a", "na"):
        return None
    s = s.replace("R$", "").replace("%", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


class Command(BaseCommand):
    help = (
        "Reanalisa todos os DocumentoCCT j\u00e1 dispon\u00edveis (com PDF no disco), "
        "reextraindo datas de vig\u00eancia e, opcionalmente, executando an\u00e1lise com IA."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sindicato-codigo",
            type=str,
            help="Filtra por c\u00f3digo de sindicato espec\u00edfico.",
        )
        parser.add_argument(
            "--com-ia",
            action="store_true",
            help="Tamb\u00e9m executa an\u00e1lise com IA para cada documento (mais lento).",
        )
        parser.add_argument(
            "--limite",
            type=int,
            default=0,
            help="Limite de documentos a processar (0 = sem limite).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula a execu\u00e7\u00e3o sem salvar no banco.",
        )

    def handle(self, *args, **options):
        sindicato_codigo = options.get("sindicato_codigo")
        com_ia = options.get("com_ia")
        limite = options.get("limite")
        dry_run = options.get("dry_run")

        queryset = DocumentoCCT.objects.filter(ativo=True).exclude(
            arquivo_pdf=""
        ).exclude(arquivo_pdf__isnull=True)

        if sindicato_codigo:
            queryset = queryset.filter(sindicato__codigo=sindicato_codigo)

        total = queryset.count()
        if limite > 0:
            queryset = queryset[:limite]
            total = min(total, limite)

        self.stdout.write(self.style.NOTICE(
            f"Documentos a reanalisar: {total}"
            + (" com IA" if com_ia else " (somente datas)")
            + (" (DRY-RUN)" if dry_run else "")
        ))

        atualizados_datas = 0
        analisados_ia = 0
        erros = 0
        sem_mudanca = 0

        for idx, doc in enumerate(queryset, start=1):
            self.stdout.write(f"\n[{idx}/{total}] #{doc.pk} — {doc.sindicato} — {doc.tipo}")

            # Resolve caminho absoluto do PDF
            caminho_pdf = doc.arquivo_pdf
            if not os.path.isabs(caminho_pdf):
                from django.conf import settings
                caminho_pdf = str(Path(settings.BASE_DIR) / caminho_pdf)

            if not os.path.exists(caminho_pdf):
                self.stdout.write(self.style.WARNING(f"  PDF n\u00e3o encontrado: {caminho_pdf}"))
                erros += 1
                continue

            # Extrai texto do PDF
            texto = extrair_texto_pdf(caminho_pdf, max_paginas=10)
            if not texto or texto.startswith("[ERRO"):
                self.stdout.write(self.style.WARNING(f"  Falha ao extrair texto do PDF."))
                erros += 1
                continue

            # --- Reextrai datas de vig\u00eancia ---
            datas = extrair_datas_do_texto(texto)
            mudou = False
            campos_atualizar = []

            if datas["data_inicio"] and doc.data_inicio_vigencia != datas["data_inicio"]:
                if not dry_run:
                    doc.data_inicio_vigencia = datas["data_inicio"]
                campos_atualizar.append("data_inicio_vigencia")
                mudou = True

            if datas["data_fim"] and doc.data_fim_vigencia != datas["data_fim"]:
                if not dry_run:
                    doc.data_fim_vigencia = datas["data_fim"]
                campos_atualizar.append("data_fim_vigencia")
                mudou = True

            if datas["data_registro_mte"] and doc.data_registro_mte != datas["data_registro_mte"]:
                if not dry_run:
                    doc.data_registro_mte = datas["data_registro_mte"]
                campos_atualizar.append("data_registro_mte")
                mudou = True

            # --- Reextrai dados complementares (data base, reajuste, contribuições) ---
            compl = extrair_dados_complementares_do_texto(texto)

            if compl["data_base"] and doc.data_base != compl["data_base"]:
                if not dry_run:
                    doc.data_base = compl["data_base"]
                if "data_base" not in campos_atualizar:
                    campos_atualizar.append("data_base")
                mudou = True

            if compl["reajuste_percentual"] is not None:
                from decimal import Decimal
                novo_valor = Decimal(str(compl["reajuste_percentual"]))
                if doc.reajuste_percentual != novo_valor:
                    if not dry_run:
                        doc.reajuste_percentual = novo_valor
                    if "reajuste_percentual" not in campos_atualizar:
                        campos_atualizar.append("reajuste_percentual")
                    mudou = True

            if compl["contribuicao_sindical_empregado"] is not None:
                from decimal import Decimal
                novo_valor = Decimal(str(compl["contribuicao_sindical_empregado"]))
                if doc.contribuicao_sindical_empregado != novo_valor:
                    if not dry_run:
                        doc.contribuicao_sindical_empregado = novo_valor
                    if "contribuicao_sindical_empregado" not in campos_atualizar:
                        campos_atualizar.append("contribuicao_sindical_empregado")
                    mudou = True

            if compl["contribuicao_sindical_patronal"] is not None:
                from decimal import Decimal
                novo_valor = Decimal(str(compl["contribuicao_sindical_patronal"]))
                if doc.contribuicao_sindical_patronal != novo_valor:
                    if not dry_run:
                        doc.contribuicao_sindical_patronal = novo_valor
                    if "contribuicao_sindical_patronal" not in campos_atualizar:
                        campos_atualizar.append("contribuicao_sindical_patronal")
                    mudou = True

            if compl["trecho_contribuicao_empregado"] is not None:
                if doc.trecho_contribuicao_empregado != compl["trecho_contribuicao_empregado"]:
                    if not dry_run:
                        doc.trecho_contribuicao_empregado = compl["trecho_contribuicao_empregado"]
                    if "trecho_contribuicao_empregado" not in campos_atualizar:
                        campos_atualizar.append("trecho_contribuicao_empregado")
                    mudou = True

            if compl["trecho_contribuicao_patronal"] is not None:
                if doc.trecho_contribuicao_patronal != compl["trecho_contribuicao_patronal"]:
                    if not dry_run:
                        doc.trecho_contribuicao_patronal = compl["trecho_contribuicao_patronal"]
                    if "trecho_contribuicao_patronal" not in campos_atualizar:
                        campos_atualizar.append("trecho_contribuicao_patronal")
                    mudou = True

            if compl["contribuicao_sindical_empregado_meses"] is not None:
                if doc.contribuicao_sindical_empregado_meses != compl["contribuicao_sindical_empregado_meses"]:
                    if not dry_run:
                        doc.contribuicao_sindical_empregado_meses = compl["contribuicao_sindical_empregado_meses"]
                    if "contribuicao_sindical_empregado_meses" not in campos_atualizar:
                        campos_atualizar.append("contribuicao_sindical_empregado_meses")
                    mudou = True

            if mudou:
                if not dry_run:
                    doc.save(update_fields=campos_atualizar)
                self.stdout.write(self.style.SUCCESS(
                    f"  {'[DRY-RUN] ' if dry_run else ''}Atualizado: {', '.join(campos_atualizar)}"
                ))
                atualizados_datas += 1
            else:
                sem_mudanca += 1

            # --- Análise com IA (opcional) ---
            if com_ia and not dry_run and analisar_cct_com_ia:
                try:
                    resultado = analisar_cct_com_ia(texto)
                    if resultado.get("erro"):
                        self.stdout.write(self.style.WARNING(f"  IA erro: {resultado['erro'][:200]}"))
                        doc.status_analise_ia = DocumentoCCT.STATUS_ANALISE_ERRO
                        doc.analise_ia_texto = resultado["erro"]
                        doc.save(update_fields=["status_analise_ia", "analise_ia_texto"])
                        erros += 1
                    else:
                        ia_json = resultado.get("resultado") or {}
                        campos_ia = [
                            "status_analise_ia",
                            "analise_ia_json",
                            "analise_ia_texto",
                            "data_analise_ia",
                        ]

                        db = _parse_data_br(ia_json.get("data_base"))
                        if db:
                            doc.data_base = db
                            if "data_base" not in campos_ia:
                                campos_ia.append("data_base")

                        vi = _parse_data_br(ia_json.get("vigencia_inicio"))
                        if vi:
                            doc.data_inicio_vigencia = vi
                            if "data_inicio_vigencia" not in campos_ia:
                                campos_ia.append("data_inicio_vigencia")

                        vf = _parse_data_br(ia_json.get("vigencia_fim"))
                        if vf:
                            doc.data_fim_vigencia = vf
                            if "data_fim_vigencia" not in campos_ia:
                                campos_ia.append("data_fim_vigencia")

                        rp = _parse_decimal(ia_json.get("reajuste_percentual"))
                        if rp is not None:
                            doc.reajuste_percentual = rp
                            if "reajuste_percentual" not in campos_ia:
                                campos_ia.append("reajuste_percentual")

                        ce = _parse_decimal(ia_json.get("contribuicao_sindical_empregado"))
                        if ce is not None:
                            doc.contribuicao_sindical_empregado = ce
                            if "contribuicao_sindical_empregado" not in campos_ia:
                                campos_ia.append("contribuicao_sindical_empregado")

                        cp = _parse_decimal(ia_json.get("contribuicao_sindical_patronal"))
                        if cp is not None:
                            doc.contribuicao_sindical_patronal = cp
                            if "contribuicao_sindical_patronal" not in campos_ia:
                                campos_ia.append("contribuicao_sindical_patronal")

                        doc.status_analise_ia = DocumentoCCT.STATUS_ANALISE_CONCLUIDO
                        doc.analise_ia_json = ia_json
                        import json
                        doc.analise_ia_texto = json.dumps(ia_json, ensure_ascii=False, indent=2)
                        from django.utils import timezone
                        doc.data_analise_ia = timezone.now()
                        doc.save(update_fields=campos_ia)
                        self.stdout.write(self.style.SUCCESS(f"  IA analisada com sucesso."))
                        analisados_ia += 1
                        # Pequena pausa para n\u00e3o sobrecarregar a API
                        time.sleep(2)
                except Exception as e_ia:
                    self.stdout.write(self.style.ERROR(f"  Erro inesperado na IA: {e_ia}"))
                    erros += 1

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.NOTICE("RESUMO:"))
        self.stdout.write(f"  Total processados:      {total}")
        self.stdout.write(self.style.SUCCESS(f"  Datas atualizadas:      {atualizados_datas}"))
        if com_ia:
            self.stdout.write(self.style.SUCCESS(f"  Analisados com IA:      {analisados_ia}"))
        self.stdout.write(f"  Sem mudan\u00e7a:            {sem_mudanca}")
        self.stdout.write(self.style.WARNING(f"  Erros:                  {erros}"))
