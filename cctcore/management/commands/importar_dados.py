import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from cctcore.models import Sindicato, Empresa, EmpresaSindicato, DocumentoCCT


def limpar_cnpj(cnpj):
    if pd.isna(cnpj):
        return ""
    return re.sub(r"\D", "", str(cnpj).strip())


class Command(BaseCommand):
    help = "Importa dados das planilhas Excel e PDFs para os modelos do cctcore"

    def handle(self, *args, **options):
        base_dir = Path(settings.BASE_DIR)
        self.importar_sindicatos(base_dir)
        self.importar_empresas(base_dir)
        self.importar_documentos(base_dir)
        self.stdout.write(self.style.SUCCESS("Importação concluída!"))

    def importar_sindicatos(self, base_dir):
        self.stdout.write("Importando sindicatos...")
        df_sist = pd.read_excel(base_dir / "sindicatosistema.xlsx")
        df_cnpjs = pd.read_excel(base_dir / "cnpjs.xlsx")

        # Normalizar colunas
        df_sist.columns = [c.strip().lower() for c in df_sist.columns]
        df_cnpjs.columns = [c.strip().lower() for c in df_cnpjs.columns]

        # Usar sindicatosistema como base (tem código, cnpj, nome)
        # Fazer merge com cnpjs.xlsx para pegar nome mais limpo se disponível
        df = df_sist.merge(df_cnpjs[["cnpj", "sindicato"]], on="cnpj", how="left", suffixes=("", "_cnpjs"))

        # Preferir nome de cnpjs.xlsx quando disponível, senão usar o de sindicatosistema
        df["nome_final"] = df["sindicato_cnpjs"].fillna(df["sindicato"])

        # Remover duplicatas de código (primeira ocorrência)
        df = df.drop_duplicates(subset=["codigo"], keep="first")

        criados = 0
        atualizados = 0

        with transaction.atomic():
            for _, row in df.iterrows():
                codigo = str(int(row["codigo"])).strip()
                cnpj = limpar_cnpj(row["cnpj"])
                nome = str(row["nome_final"]).strip()

                sindicato, created = Sindicato.objects.update_or_create(
                    codigo=codigo,
                    defaults={"cnpj": cnpj, "nome": nome},
                )
                if created:
                    criados += 1
                else:
                    atualizados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"  Sindicatos: {criados} criados, {atualizados} atualizados"
            )
        )

    def importar_empresas(self, base_dir):
        self.stdout.write("Importando empresas...")
        df = pd.read_excel(base_dir / "empresasindicato.xlsx")
        df.columns = [c.strip().lower() for c in df.columns]

        empresas_criadas = 0
        empresas_atualizadas = 0
        relacoes_criadas = 0

        with transaction.atomic():
            for _, row in df.iterrows():
                codempresa = str(int(row["codempresa"])).strip()
                nome_empresa = str(row["empresa"]).strip()

                empresa, created = Empresa.objects.update_or_create(
                    codigo=codempresa,
                    defaults={"nome": nome_empresa},
                )
                if created:
                    empresas_criadas += 1
                else:
                    empresas_atualizadas += 1

                # Relação com sindicato 1
                if pd.notna(row.get("codsindicato")):
                    cod_sind = str(int(row["codsindicato"])).strip()
                    if cod_sind != "0":
                        try:
                            sindicato = Sindicato.objects.get(codigo=cod_sind)
                            _, rcreated = EmpresaSindicato.objects.get_or_create(
                                empresa=empresa, sindicato=sindicato
                            )
                            if rcreated:
                                relacoes_criadas += 1
                        except Sindicato.DoesNotExist:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"    Sindicato {cod_sind} não encontrado para empresa {codempresa}"
                                )
                            )

                # Relação com sindicato 2
                if pd.notna(row.get("codsindicato2")):
                    cod_sind2 = str(int(row["codsindicato2"])).strip()
                    if cod_sind2 != "0":
                        try:
                            sindicato2 = Sindicato.objects.get(codigo=cod_sind2)
                            _, rcreated = EmpresaSindicato.objects.get_or_create(
                                empresa=empresa, sindicato=sindicato2
                            )
                            if rcreated:
                                relacoes_criadas += 1
                        except Sindicato.DoesNotExist:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"    Sindicato {cod_sind2} não encontrado para empresa {codempresa}"
                                )
                            )

        self.stdout.write(
            self.style.SUCCESS(
                f"  Empresas: {empresas_criadas} criadas, {empresas_atualizadas} atualizadas, {relacoes_criadas} relações criadas"
            )
        )

    def importar_documentos(self, base_dir):
        self.stdout.write("Importando documentos CCT...")
        convencoes_dir = base_dir / "convencoes"
        if not convencoes_dir.exists():
            self.stdout.write(self.style.ERROR("  Pasta convencoes/ não encontrada"))
            return

        padrao = re.compile(r"^(\d+)-(CCT|TA-CCT)-(.+)-(\d{2}-\d{2}-\d{4})\.pdf$")
        docs_criados = 0
        docs_existentes = 0
        ignorados = 0

        with transaction.atomic():
            for arquivo in convencoes_dir.iterdir():
                if not arquivo.is_file() or arquivo.suffix.lower() != ".pdf":
                    continue

                nome = arquivo.name
                match = padrao.match(nome)
                if not match:
                    self.stdout.write(
                        self.style.WARNING(f"  Arquivo não corresponde ao padrão: {nome}")
                    )
                    ignorados += 1
                    continue

                codigo, tipo, _, data_str = match.groups()
                codigo = codigo.strip()

                try:
                    data_vigencia = datetime.strptime(data_str, "%d-%m-%Y").date()
                except ValueError:
                    self.stdout.write(
                        self.style.WARNING(f"  Data inválida em {nome}: {data_str}")
                    )
                    ignorados += 1
                    continue

                try:
                    sindicato = Sindicato.objects.get(codigo=codigo)
                except Sindicato.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Sindicato {codigo} não encontrado para arquivo {nome}"
                        )
                    )
                    ignorados += 1
                    continue

                # Caminho relativo ao BASE_DIR
                caminho_relativo = str(arquivo.relative_to(base_dir))

                doc, created = DocumentoCCT.objects.get_or_create(
                    sindicato=sindicato,
                    tipo=tipo,
                    data_inicio_vigencia=data_vigencia,
                    defaults={
                        "arquivo_pdf": caminho_relativo,
                        "status_extracao": DocumentoCCT.STATUS_EXTRAIDO,
                    },
                )
                if not created:
                    # Já existe: atualiza caminho e status se necessário
                    doc.arquivo_pdf = caminho_relativo
                    if doc.status_extracao == DocumentoCCT.STATUS_PENDENTE:
                        doc.status_extracao = DocumentoCCT.STATUS_EXTRAIDO
                    doc.save()
                    docs_existentes += 1
                else:
                    docs_criados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"  Documentos: {docs_criados} criados, {docs_existentes} já existiam, {ignorados} ignorados"
            )
        )
