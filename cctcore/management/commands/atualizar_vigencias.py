import os
import re
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from pathlib import Path

from cctcore.models import DocumentoCCT
from cctcore.services import extrair_texto_pdf


def parse_data_br(data_str):
    """Converte string de data brasileira para objeto date."""
    if not data_str:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(data_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def extrair_datas_do_texto(texto):
    """
    Extrai datas de vigência (início, fim) e registro MTE do texto de uma CCT.
    Retorna dict com as chaves: data_inicio, data_fim, data_registro_mte.
    """
    resultado = {
        "data_inicio": None,
        "data_fim": None,
        "data_registro_mte": None,
    }

    if not texto or len(texto) < 50:
        return resultado

    texto_upper = texto.upper()

    # ============================================================
    # 1. VIGÊNCIA - múltiplas estratégias
    # ============================================================

    # Estratégia 1a: "VIGENCIA DE DD/MM/AAAA A DD/MM/AAAA"
    m = re.search(
        r'VIGEN[CGÇ][IA]*\s*(?:DE)?\s*(\d{2}[/-]\d{2}[/-]\d{4})\s*(?:A|AT[EÉ]|–|-)\s*(\d{2}[/-]\d{2}[/-]\d{4})',
        texto_upper
    )
    if m:
        resultado["data_inicio"] = parse_data_br(m.group(1))
        resultado["data_fim"] = parse_data_br(m.group(2))

    # Estratégia 1b: "VIGÊNCIA: DD/MM/AAAA - DD/MM/AAAA"
    if not resultado["data_inicio"]:
        m = re.search(
            r'VIGEN[CGÇ][IA]*\s*[:\-]\s*(\d{2}[/-]\d{2}[/-]\d{4})\s*(?:A|AT[EÉ]|–|-)\s*(\d{2}[/-]\d{2}[/-]\d{4})',
            texto_upper
        )
        if m:
            resultado["data_inicio"] = parse_data_br(m.group(1))
            resultado["data_fim"] = parse_data_br(m.group(2))

    # Estratégia 1c: "PERÍODO DE VIGÊNCIA" ou "PRAZO DE VIGÊNCIA"
    if not resultado["data_inicio"]:
        m = re.search(
            r'(?:PER[IÍ]ODO|PRAZO)\s*DE\s*VIGEN[CGÇ][IA]*.*?([\d]{2}[/-][\d]{2}[/-][\d]{4}).*?(?:A|AT[EÉ]|–|-).*?([\d]{2}[/-][\d]{2}[/-][\d]{4})',
            texto_upper, re.DOTALL
        )
        if m:
            resultado["data_inicio"] = parse_data_br(m.group(1))
            resultado["data_fim"] = parse_data_br(m.group(2))

    # Estratégia 1d: Duas datas próximas em contexto de vigência (fallback)
    if not resultado["data_inicio"]:
        # Procura bloco com a palavra vigência e pega as duas primeiras datas
        blocos = re.split(r'VIGEN[CGÇ][IA]*', texto_upper)
        if len(blocos) > 1:
            for bloco in blocos[1:3]:
                datas = re.findall(r'(\d{2}[/-]\d{2}[/-]\d{4})', bloco[:500])
                if len(datas) >= 2:
                    resultado["data_inicio"] = parse_data_br(datas[0])
                    resultado["data_fim"] = parse_data_br(datas[1])
                    break
                elif len(datas) == 1:
                    resultado["data_inicio"] = parse_data_br(datas[0])
                    break

    # Estratégia 1e: Se só achou uma data, tenta achar outra no documento inteiro como fim
    if resultado["data_inicio"] and not resultado["data_fim"]:
        # Procura por "até" ou "a" seguido de data após a data de início no texto
        pos = texto_upper.find(str(resultado["data_inicio"]).replace("-", "/"))
        if pos >= 0:
            trecho = texto_upper[pos:pos+800]
            m_fim = re.search(r'(?:AT[EÉ]|A)\s*(\d{2}[/-]\d{2}[/-]\d{4})', trecho)
            if m_fim:
                resultado["data_fim"] = parse_data_br(m_fim.group(1))

    # ============================================================
    # 2. DATA DE REGISTRO NO MTE
    # ============================================================

    # Estratégia 2a: "DATA DE REGISTRO NO MTE" ou "REGISTRO NO MTE"
    m = re.search(
        r'DATA\s*DE\s*REGISTRO\s*(?:NO\s*MTE)?\s*[:\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})',
        texto_upper
    )
    if m:
        resultado["data_registro_mte"] = parse_data_br(m.group(1))

    # Estratégia 2b: "REGISTRADO EM DD/MM/AAAA NO MTE"
    if not resultado["data_registro_mte"]:
        m = re.search(
            r'REGISTRAD[OA]\s+(?:EM\s+)?(\d{2}[/-]\d{2}[/-]\d{4}).*?MTE',
            texto_upper
        )
        if m:
            resultado["data_registro_mte"] = parse_data_br(m.group(1))

    # Estratégia 2c: "REGISTRO: DD/MM/AAAA" próximo de "MTE" ou "MINISTÉRIO"
    if not resultado["data_registro_mte"]:
        m = re.search(
            r'REGISTRO\s*[:\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})',
            texto_upper
        )
        if m:
            # Verifica se há menção a MTE/ministério em um raio de 300 chars
            pos_reg = texto_upper.find("REGISTRO")
            if pos_reg >= 0:
                trecho = texto_upper[max(0, pos_reg-200):pos_reg+300]
                if "MTE" in trecho or "MINISTERIO" in trecho or "MINISTÉRIO" in trecho:
                    resultado["data_registro_mte"] = parse_data_br(m.group(1))

    # Estratégia 2d: "Protocolo" ou "Processo" com data (algumas CCTs usam esse formato)
    if not resultado["data_registro_mte"]:
        m = re.search(
            r'(?:PROTOCOLO|PROCESSO)\s*(?:N[º°]?\s*)?\d+.*?([\d]{2}[/-][\d]{2}[/-][\d]{4})',
            texto_upper, re.DOTALL
        )
        if m:
            # Só usa se não houver outra data de registro
            candidata = parse_data_br(m.group(1))
            # Evita confundir com data de início de vigência
            if candidata != resultado["data_inicio"]:
                resultado["data_registro_mte"] = candidata

    return resultado


class Command(BaseCommand):
    help = (
        "Atualiza as datas de vigência (início, fim) e registro MTE "
        "dos DocumentoCCT já existentes no banco, extraindo do PDF."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sindicato-codigo",
            type=str,
            help="Filtra por código de sindicato específico.",
        )
        parser.add_argument(
            "--apenas-vazios",
            action="store_true",
            help="Só processa documentos que ainda não têm data_fim_vigencia ou data_registro_mte.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula a execução sem salvar no banco.",
        )
        parser.add_argument(
            "--limite",
            type=int,
            default=0,
            help="Limite de documentos a processar (0 = sem limite).",
        )

    def handle(self, *args, **options):
        sindicato_codigo = options.get("sindicato_codigo")
        apenas_vazios = options.get("apenas_vazios")
        dry_run = options.get("dry_run")
        limite = options.get("limite")

        queryset = DocumentoCCT.objects.filter(ativo=True).exclude(
            arquivo_pdf=""
        ).exclude(arquivo_pdf__isnull=True)

        if sindicato_codigo:
            queryset = queryset.filter(sindicato__codigo=sindicato_codigo)

        if apenas_vazios:
            queryset = queryset.filter(
                data_fim_vigencia__isnull=True
            ) | queryset.filter(data_registro_mte__isnull=True)

        total = queryset.count()
        if limite > 0:
            queryset = queryset[:limite]
            total = min(total, limite)

        self.stdout.write(self.style.NOTICE(
            f"Documentos a processar: {total}"
            + (" (DRY-RUN)" if dry_run else "")
        ))

        atualizados = 0
        sem_mudanca = 0
        erro_pdf = 0

        for idx, doc in enumerate(queryset, start=1):
            self.stdout.write(f"\n[{idx}/{total}] #{doc.pk} — {doc.sindicato} — {doc.tipo}")

            # Resolve caminho absoluto do PDF
            caminho_pdf = doc.arquivo_pdf
            if not os.path.isabs(caminho_pdf):
                from django.conf import settings
                caminho_pdf = str(Path(settings.BASE_DIR) / caminho_pdf)

            if not os.path.exists(caminho_pdf):
                self.stdout.write(self.style.WARNING(f"  PDF não encontrado: {caminho_pdf}"))
                continue

            # Extrai texto do PDF
            texto = extrair_texto_pdf(caminho_pdf, max_paginas=10)
            if not texto or texto.startswith("[ERRO"):
                self.stdout.write(self.style.WARNING(f"  Falha ao extrair texto do PDF."))
                erro_pdf += 1
                continue

            # Extrai datas do texto
            datas = extrair_datas_do_texto(texto)

            # Log do que foi encontrado
            encontrado = []
            if datas["data_inicio"]:
                encontrado.append(f"início={datas['data_inicio']}")
            if datas["data_fim"]:
                encontrado.append(f"fim={datas['data_fim']}")
            if datas["data_registro_mte"]:
                encontrado.append(f"registro_mte={datas['data_registro_mte']}")

            if encontrado:
                self.stdout.write(f"  Encontrado: {', '.join(encontrado)}")
            else:
                self.stdout.write(self.style.WARNING(f"  Nenhuma data encontrada no texto."))

            # Verifica se houve mudança real
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

            if mudou:
                if not dry_run:
                    doc.save(update_fields=campos_atualizar)
                self.stdout.write(self.style.SUCCESS(
                    f"  {'[DRY-RUN] ' if dry_run else ''}Atualizado: {', '.join(campos_atualizar)}"
                ))
                atualizados += 1
            else:
                sem_mudanca += 1

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.NOTICE("RESUMO:"))
        self.stdout.write(f"  Total processados: {total}")
        self.stdout.write(self.style.SUCCESS(f"  Com atualização:   {atualizados}"))
        self.stdout.write(f"  Sem mudança:       {sem_mudanca}")
        self.stdout.write(self.style.WARNING(f"  Erro no PDF:       {erro_pdf}"))
