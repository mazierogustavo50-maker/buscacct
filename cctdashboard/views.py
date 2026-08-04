from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import FileResponse, Http404, HttpResponse
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from pathlib import Path
import pandas as pd
import subprocess
import sys
import os
import re
import unicodedata

from cctcore.models import Sindicato, Empresa, EmpresaSindicato, DocumentoCCT
from cctbuscador.models import ExecucaoScraper, AgendamentoScraper
from .forms import SindicatoForm, EmpresaForm, ImportarSindicatosForm, ImportarEmpresasForm
from cctcore.services import extrair_texto_pdf, garantir_ocr_pdf


@login_required
def home(request):
    total_sindicatos = Sindicato.objects.count()
    total_empresas = Empresa.objects.count()
    total_cct = DocumentoCCT.objects.filter(tipo=DocumentoCCT.TIPO_CCT).count()
    total_ta_cct = DocumentoCCT.objects.filter(tipo=DocumentoCCT.TIPO_TA_CCT).count()
    execucoes_recentes = ExecucaoScraper.objects.all()[:5]

    # Dados para gráfico de documentos por tipo
    documentos_por_tipo = {
        "labels": ["CCT", "TA-CCT"],
        "data": [total_cct, total_ta_cct],
    }

    # Dados para gráfico de documentos por sindicato (top 10)
    docs_por_sindicato = (
        Sindicato.objects.annotate(total_docs=Count("documentos"))
        .filter(total_docs__gt=0)
        .order_by("-total_docs")[:10]
    )
    sindicato_labels = [s.codigo for s in docs_por_sindicato]
    sindicato_data = [s.total_docs for s in docs_por_sindicato]

    # Lista de não encontrados da execução mais recente (se houver)
    ultima_execucao = ExecucaoScraper.objects.first()
    nao_encontrados = []
    if ultima_execucao and ultima_execucao.nao_encontrados_json:
        for item in ultima_execucao.nao_encontrados_json:
            if isinstance(item, dict):
                nao_encontrados.append(item)
            elif isinstance(item, (list, tuple)):
                nao_encontrados.append({
                    "cnpj": item[0] if len(item) > 0 else "",
                    "sindicato": item[1] if len(item) > 1 else "",
                    "nome": item[1] if len(item) > 1 else "",
                })
            else:
                nao_encontrados.append({"cnpj": str(item), "sindicato": "", "nome": ""})

    context = {
        "total_sindicatos": total_sindicatos,
        "total_empresas": total_empresas,
        "total_cct": total_cct,
        "total_ta_cct": total_ta_cct,
        "execucoes_recentes": execucoes_recentes,
        "documentos_por_tipo": documentos_por_tipo,
        "sindicato_labels": sindicato_labels,
        "sindicato_data": sindicato_data,
        "nao_encontrados": nao_encontrados,
    }
    return render(request, "cctdashboard/home.html", context)


@login_required
def relatorio_execucoes(request):
    """Relatório completo de execuções do scraper com não encontrados."""
    execucoes = ExecucaoScraper.objects.all()

    # Normaliza nao_encontrados_json para cada execução
    execucoes_norm = []
    for execucao in execucoes:
        nao_encontrados = []
        if execucao.nao_encontrados_json:
            for item in execucao.nao_encontrados_json:
                if isinstance(item, dict):
                    nao_encontrados.append(item)
                elif isinstance(item, (list, tuple)):
                    nao_encontrados.append({
                        "cnpj": item[0] if len(item) > 0 else "",
                        "sindicato": item[1] if len(item) > 1 else "",
                        "nome": item[1] if len(item) > 1 else "",
                    })
                else:
                    nao_encontrados.append({"cnpj": str(item), "sindicato": "", "nome": ""})
        execucoes_norm.append({
            "execucao": execucao,
            "nao_encontrados": nao_encontrados,
        })

    # Totais gerais
    total_execucoes = execucoes.count()
    total_baixados = sum(e.total_baixados for e in execucoes)
    total_ja_existentes = sum(e.total_ja_existentes for e in execucoes)
    total_nao_encontrados = sum(e.total_nao_encontrados for e in execucoes)

    context = {
        "execucoes_norm": execucoes_norm,
        "total_execucoes": total_execucoes,
        "total_baixados": total_baixados,
        "total_ja_existentes": total_ja_existentes,
        "total_nao_encontrados": total_nao_encontrados,
    }
    return render(request, "cctdashboard/relatorio.html", context)


@login_required
def lista_sindicatos(request):
    queryset = Sindicato.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(nome__icontains=q) | Q(codigo__icontains=q) | Q(cnpj__icontains=q) | Q(apelido__icontains=q)
        )

    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "q": q,
    }
    return render(request, "cctdashboard/lista_sindicatos.html", context)


@login_required
def detalhe_sindicato(request, pk):
    sindicato = get_object_or_404(Sindicato, pk=pk)
    empresas = (
        Empresa.objects.filter(sindicatos__sindicato=sindicato)
        .distinct()
        .order_by("nome")
    )
    documentos = sindicato.documentos.filter(ativo=True)

    context = {
        "sindicato": sindicato,
        "empresas": empresas,
        "documentos": documentos,
    }
    return render(request, "cctdashboard/detalhe_sindicato.html", context)


@login_required
def criar_sindicato(request):
    if request.method == "POST":
        form = SindicatoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Sindicato cadastrado com sucesso.")
            return redirect("cctdashboard:lista_sindicatos")
    else:
        form = SindicatoForm()
    return render(request, "cctdashboard/form_sindicato.html", {"form": form, "titulo": "Novo Sindicato"})


@login_required
def editar_sindicato(request, pk):
    sindicato = get_object_or_404(Sindicato, pk=pk)
    if request.method == "POST":
        form = SindicatoForm(request.POST, instance=sindicato)
        if form.is_valid():
            form.save()
            messages.success(request, "Sindicato atualizado com sucesso.")
            return redirect("cctdashboard:detalhe_sindicato", pk=pk)
    else:
        form = SindicatoForm(instance=sindicato)
    return render(request, "cctdashboard/form_sindicato.html", {"form": form, "titulo": "Editar Sindicato", "sindicato": sindicato})


@login_required
def excluir_sindicato(request, pk):
    sindicato = get_object_or_404(Sindicato, pk=pk)
    if request.method == "POST":
        sindicato.delete()
        messages.success(request, "Sindicato excluído com sucesso.")
        return redirect("cctdashboard:lista_sindicatos")
    return render(request, "cctdashboard/confirmar_exclusao.html", {
        "objeto": sindicato,
        "tipo": "sindicato",
        "voltar_url": "cctdashboard:detalhe_sindicato",
        "voltar_pk": pk,
    })


@login_required
def importar_sindicatos(request):
    if request.method == "POST":
        form = ImportarSindicatosForm(request.POST, request.FILES)
        if form.is_valid():
            arquivo = request.FILES["arquivo"]
            try:
                df = pd.read_excel(arquivo, dtype=str)
                df.columns = [str(c).strip().lower().replace(" ", "").replace("_", "").replace("-", "") for c in df.columns]

                # Mapeamento flexível de colunas
                col_codigo = next((c for c in df.columns if c in ("codigo", "codigosindicato", "codsindicato", "cod")), None)
                col_nome = next((c for c in df.columns if c in ("nome", "nomesindicato", "nomedosindicato", "sindicato")), None)
                col_cnpj = next((c for c in df.columns if c in ("cnpj", "cnpjsindicato", "cnpjdosindicato")), None)

                if not col_codigo or not col_nome:
                    messages.error(request, "O arquivo deve conter as colunas: código e nome do sindicato.")
                    return render(request, "cctdashboard/importar_sindicatos.html", {"form": form})

                criados = 0
                atualizados = 0
                erros = []

                for idx, row in df.iterrows():
                    try:
                        codigo = str(row[col_codigo]).strip() if pd.notna(row[col_codigo]) else ""
                        nome = str(row[col_nome]).strip() if pd.notna(row[col_nome]) else ""
                        cnpj = str(row[col_cnpj]).strip() if col_cnpj and pd.notna(row[col_cnpj]) else ""
                        if not codigo or not nome:
                            continue

                        # Remove formatação do CNPJ
                        cnpj = "".join(filter(str.isdigit, cnpj))

                        obj, created = Sindicato.objects.update_or_create(
                            codigo=codigo,
                            defaults={"nome": nome, "cnpj": cnpj},
                        )
                        if created:
                            criados += 1
                        else:
                            atualizados += 1
                    except Exception as e:
                        erros.append(f"Linha {idx + 2}: {e}")

                msg = f"Importação concluída. Criados: {criados}, Atualizados: {atualizados}."
                if erros:
                    msg += f" Erros: {len(erros)}."
                messages.success(request, msg)
                if erros:
                    for erro in erros[:10]:
                        messages.warning(request, erro)
                return redirect("cctdashboard:lista_sindicatos")
            except Exception as e:
                messages.error(request, f"Erro ao processar arquivo: {e}")
    else:
        form = ImportarSindicatosForm()
    return render(request, "cctdashboard/importar_sindicatos.html", {"form": form})


@login_required
def lista_empresas(request):
    # Por padrao mostra apenas ativas; ?inativas=1 mostra apenas inativas
    mostrar_inativas = request.GET.get("inativas", "").strip() == "1"
    queryset = Empresa.objects.all()
    if mostrar_inativas:
        queryset = queryset.filter(ativo=False)
    else:
        queryset = queryset.filter(ativo=True)

    q = request.GET.get("q", "").strip()
    sem_sindicato = request.GET.get("sem_sindicato", "").strip() == "1"

    if q:
        queryset = queryset.filter(
            Q(nome__icontains=q) | Q(codigo__icontains=q)
        )

    if sem_sindicato:
        queryset = queryset.filter(sindicatos__isnull=True)

    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "q": q,
        "mostrar_inativas": mostrar_inativas,
        "sem_sindicato": sem_sindicato,
    }
    return render(request, "cctdashboard/lista_empresas.html", context)


@login_required
def detalhe_empresa(request, pk):
    empresa = get_object_or_404(Empresa, pk=pk)
    sindicatos = (
        Sindicato.objects.filter(empresas__empresa=empresa)
        .distinct()
        .order_by("nome")
    )
    documentos_cct = (
        DocumentoCCT.objects.filter(empresas_vinculadas__empresa=empresa, ativo=True)
        .distinct()
        .order_by("-data_inicio_vigencia")
    )

    context = {
        "empresa": empresa,
        "sindicatos": sindicatos,
        "documentos_cct": documentos_cct,
    }
    return render(request, "cctdashboard/detalhe_empresa.html", context)


@login_required
def criar_empresa(request):
    if request.method == "POST":
        form = EmpresaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Empresa cadastrada com sucesso.")
            return redirect("cctdashboard:lista_empresas")
    else:
        form = EmpresaForm()
    return render(request, "cctdashboard/form_empresa.html", {"form": form, "titulo": "Nova Empresa"})


@login_required
def editar_empresa(request, pk):
    empresa = get_object_or_404(Empresa, pk=pk)
    if request.method == "POST":
        form = EmpresaForm(request.POST, instance=empresa)
        if form.is_valid():
            form.save()
            messages.success(request, "Empresa atualizada com sucesso.")
            return redirect("cctdashboard:detalhe_empresa", pk=pk)
    else:
        form = EmpresaForm(instance=empresa)
    return render(request, "cctdashboard/form_empresa.html", {"form": form, "titulo": "Editar Empresa", "empresa": empresa})


@login_required
def excluir_empresa(request, pk):
    empresa = get_object_or_404(Empresa, pk=pk)
    if request.method == "POST":
        empresa.delete()
        messages.success(request, "Empresa excluída com sucesso.")
        return redirect("cctdashboard:lista_empresas")
    return render(request, "cctdashboard/confirmar_exclusao.html", {
        "objeto": empresa,
        "tipo": "empresa",
        "voltar_url": "cctdashboard:detalhe_empresa",
        "voltar_pk": pk,
    })


@login_required
@require_POST
def inativar_empresa(request, pk):
    empresa = get_object_or_404(Empresa, pk=pk)
    empresa.ativo = False
    empresa.save(update_fields=["ativo"])
    messages.success(request, "Empresa inativada com sucesso.")
    return redirect("cctdashboard:detalhe_empresa", pk=pk)


@login_required
@require_POST
def reativar_empresa(request, pk):
    empresa = get_object_or_404(Empresa, pk=pk)
    empresa.ativo = True
    empresa.save(update_fields=["ativo"])
    messages.success(request, "Empresa reativada com sucesso.")
    return redirect("cctdashboard:detalhe_empresa", pk=pk)


@login_required
def importar_empresas(request):
    if request.method == "POST":
        form = ImportarEmpresasForm(request.POST, request.FILES)
        if form.is_valid():
            arquivo = request.FILES["arquivo"]
            try:
                df = pd.read_excel(arquivo, dtype=str)
                df.columns = [str(c).strip().lower().replace(" ", "").replace("_", "").replace("-", "") for c in df.columns]

                col_codempresa = next((c for c in df.columns if c in ("codempresa", "codigoempresa", "codigo", "codemp")), None)
                col_nomeempresa = next((c for c in df.columns if c in ("nomeempresa", "nome", "empresa", "razaosocial")), None)
                col_cods1 = next((c for c in df.columns if c in ("codsindicato", "codsindicato1", "sindicato1", "sindicato")), None)
                col_cods2 = next((c for c in df.columns if c in ("codsindicato2", "sindicato2")), None)
                col_cods3 = next((c for c in df.columns if c in ("codsindicato3", "sindicato3")), None)

                if not col_codempresa or not col_nomeempresa:
                    messages.error(request, "O arquivo deve conter as colunas: codempresa e nomeempresa.")
                    return render(request, "cctdashboard/importar_empresas.html", {"form": form})

                criados = 0
                atualizados = 0
                erros = []

                for idx, row in df.iterrows():
                    try:
                        codigo = str(row[col_codempresa]).strip() if pd.notna(row[col_codempresa]) else ""
                        nome = str(row[col_nomeempresa]).strip() if pd.notna(row[col_nomeempresa]) else ""
                        if not codigo or not nome:
                            continue

                        empresa, created = Empresa.objects.update_or_create(
                            codigo=codigo,
                            defaults={"nome": nome},
                        )
                        if created:
                            criados += 1
                        else:
                            atualizados += 1

                        # Vínculos com sindicatos
                        codigos_sind = []
                        for col in (col_cods1, col_cods2, col_cods3):
                            if col and pd.notna(row[col]):
                                val = str(row[col]).strip()
                                if val:
                                    codigos_sind.append(val)

                        # Remove duplicados mantendo ordem
                        codigos_sind = list(dict.fromkeys(codigos_sind))

                        # Sincroniza vínculos
                        EmpresaSindicato.objects.filter(empresa=empresa).delete()
                        for cod_sind in codigos_sind:
                            try:
                                sindicato = Sindicato.objects.get(codigo=cod_sind)
                                EmpresaSindicato.objects.get_or_create(empresa=empresa, sindicato=sindicato)
                            except Sindicato.DoesNotExist:
                                erros.append(f"Linha {idx + 2}: sindicato código '{cod_sind}' não encontrado.")

                    except Exception as e:
                        erros.append(f"Linha {idx + 2}: {e}")

                msg = f"Importação concluída. Criadas: {criados}, Atualizadas: {atualizados}."
                if erros:
                    msg += f" Avisos: {len(erros)}."
                messages.success(request, msg)
                if erros:
                    for erro in erros[:10]:
                        messages.warning(request, erro)
                return redirect("cctdashboard:lista_empresas")
            except Exception as e:
                messages.error(request, f"Erro ao processar arquivo: {e}")
    else:
        form = ImportarEmpresasForm()
    return render(request, "cctdashboard/importar_empresas.html", {"form": form})


@login_required
def lista_documentos(request):
    # Por padrão mostra apenas ativos; ?inativos=1 mostra apenas inativos
    mostrar_inativos = request.GET.get("inativos", "").strip() == "1"
    queryset = DocumentoCCT.objects.select_related("sindicato").all()
    if mostrar_inativos:
        queryset = queryset.filter(ativo=False)
    else:
        queryset = queryset.filter(ativo=True)

    tipo = request.GET.get("tipo", "").strip()
    status = request.GET.get("status", "").strip()
    sindicato_id = request.GET.get("sindicato", "").strip()
    q = request.GET.get("q", "").strip()
    ordenar = request.GET.get("ordenar", "").strip()

    if tipo:
        queryset = queryset.filter(tipo=tipo)
    if status:
        queryset = queryset.filter(status_extracao=status)
    if sindicato_id:
        queryset = queryset.filter(sindicato_id=sindicato_id)
    if q:
        queryset = queryset.filter(
            Q(sindicato__nome__icontains=q)
            | Q(sindicato__codigo__icontains=q)
        )

    # Ordenação
    ordenacao_valida = {
        "inicio_vigencia": "data_inicio_vigencia",
        "-inicio_vigencia": "-data_inicio_vigencia",
        "fim_vigencia": "data_fim_vigencia",
        "-fim_vigencia": "-data_fim_vigencia",
        "registro_mte": "data_registro_mte",
        "-registro_mte": "-data_registro_mte",
        "tipo": "tipo",
        "-tipo": "-tipo",
        "status": "status_extracao",
        "-status": "-status_extracao",
    }
    if ordenar in ordenacao_valida:
        queryset = queryset.order_by(ordenacao_valida[ordenar])
    else:
        queryset = queryset.order_by("-data_inicio_vigencia")

    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Para o filtro de sindicato
    sindicatos = Sindicato.objects.order_by("nome")

    context = {
        "page_obj": page_obj,
        "tipo": tipo,
        "status": status,
        "sindicato_id": sindicato_id,
        "q": q,
        "sindicatos": sindicatos,
        "mostrar_inativos": mostrar_inativos,
        "ordenar": ordenar,
    }
    return render(request, "cctdashboard/lista_documentos.html", context)


@login_required
def detalhe_documento(request, pk):
    documento = get_object_or_404(DocumentoCCT, pk=pk)
    context = {
        "documento": documento,
    }
    return render(request, "cctdashboard/detalhe_documento.html", context)


@login_required
def ver_pdf(request, pk):
    """Serve o arquivo PDF do documento via FileResponse."""
    documento = get_object_or_404(DocumentoCCT, pk=pk)
    if not documento.arquivo_pdf:
        raise Http404("Documento não possui arquivo PDF.")

    # Resolve o caminho absoluto a partir do BASE_DIR (funciona em Docker e local)
    caminho_relativo = documento.arquivo_pdf
    if os.path.isabs(caminho_relativo):
        caminho = Path(caminho_relativo)
    else:
        caminho = Path(settings.BASE_DIR) / caminho_relativo

    if not caminho.exists():
        raise Http404(f"Arquivo PDF não encontrado: {caminho}")

    # Verifica se é realmente um PDF (pelo header)
    try:
        with caminho.open("rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                raise Http404("Arquivo não é um PDF válido.")
    except Exception:
        raise Http404("Não foi possível ler o arquivo PDF.")

    as_attachment = request.GET.get("download") == "1"

    response = FileResponse(
        caminho.open("rb"),
        content_type="application/pdf",
        as_attachment=as_attachment,
        filename=caminho.name if as_attachment else None,
    )

    # Headers para forçar visualização inline correta no navegador
    response["Content-Length"] = caminho.stat().st_size
    response["Accept-Ranges"] = "bytes"
    response["X-Content-Type-Options"] = "nosniff"

    return response


@login_required
def execucoes_scraper(request):
    queryset = ExecucaoScraper.objects.all()
    ordenar = request.GET.get("ordenar", "").strip()

    ordenacao_valida = {
        "data_inicio": "data_inicio",
        "-data_inicio": "-data_inicio",
        "data_fim": "data_fim",
        "-data_fim": "-data_fim",
        "status": "status",
        "-status": "-status",
    }
    if ordenar in ordenacao_valida:
        queryset = queryset.order_by(ordenacao_valida[ordenar])
    else:
        queryset = queryset.order_by("-data_inicio")

    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    response = render(request, "cctdashboard/execucoes_scraper.html", {
        "page_obj": page_obj,
        "ordenar": ordenar,
    })
    # Anti-cache para evitar que o navegador mostre lista desatualizada após iniciar nova execução
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@login_required
@require_POST
def executar_scraper(request):
    """Inicia o scraper em background via subprocess."""
    from cctbuscador.utils import iniciar_scraper_background

    headless = request.POST.get("headless", "on") == "on"
    forcar = request.POST.get("forcar") == "on"
    sindicato_codigo = request.POST.get("sindicato_codigo", "").strip()

    # Cria registro da execução antes de iniciar o subprocess
    execucao = ExecucaoScraper.objects.create(
        status=ExecucaoScraper.STATUS_EM_ANDAMENTO,
    )

    try:
        proc, log_path = iniciar_scraper_background(
            execucao,
            headless=headless,
            forcar=forcar,
            sindicato_codigo=sindicato_codigo,
        )
        messages.success(
            request,
            f"Scraper iniciado em background (PID {proc.pid}). Acompanhe na lista de execuções."
        )
    except Exception as e:
        execucao.status = ExecucaoScraper.STATUS_ERRO
        execucao.log_texto = str(e)
        execucao.data_fim = timezone.now()
        execucao.save(update_fields=["status", "log_texto", "data_fim"])
        messages.error(request, f"Erro ao iniciar o scraper: {e}")

    return redirect("cctdashboard:execucoes_scraper")


@login_required
@require_POST
def abortar_scraper(request, pk):
    """Marca execução para abortar e mata o processo e todos os filhos (Chrome)."""
    execucao = get_object_or_404(ExecucaoScraper, pk=pk)

    if execucao.status != ExecucaoScraper.STATUS_EM_ANDAMENTO:
        messages.warning(request, f"Execução #{execucao.id} não está em andamento.")
        return redirect("cctdashboard:detalhe_execucao", pk=pk)

    execucao.abortar = True
    execucao.save(update_fields=["abortar"])

    if execucao.pid:
        try:
            import psutil
            import signal
            parent = psutil.Process(execucao.pid)
            # Mata todos os filhos primeiro (Chrome, chromedriver)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            # Espera até 3s para os filhos morrerem
            gone, alive = psutil.wait_procs(children, timeout=3)
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
            # Manda SIGTERM para o processo pai
            try:
                parent.terminate()
                parent.wait(timeout=3)
            except psutil.TimeoutExpired:
                parent.kill()
                parent.wait(timeout=3)
            except psutil.NoSuchProcess:
                pass
            # Atualiza status no banco já que o processo foi morto
            execucao.status = ExecucaoScraper.STATUS_ABORTADO
            execucao.data_fim = timezone.now()
            execucao.save(update_fields=["status", "data_fim"])
            messages.success(
                request,
                f"Execução #{execucao.id} abortada. Processo {execucao.pid} e {len(children)} filho(s) finalizado(s)."
            )
        except psutil.NoSuchProcess:
            # Processo já morreu
            execucao.status = ExecucaoScraper.STATUS_ABORTADO
            execucao.data_fim = timezone.now()
            execucao.save(update_fields=["status", "data_fim"])
            messages.warning(request, f"Processo {execucao.pid} já havia finalizado. Execução marcada como abortada.")
            return redirect("cctdashboard:detalhe_execucao", pk=pk)
        except ImportError:
            # Fallback sem psutil
            import signal
            try:
                os.kill(execucao.pid, signal.SIGTERM)
                messages.success(request, f"Sinal de término enviado para o processo {execucao.pid}.")
            except ProcessLookupError:
                execucao.status = ExecucaoScraper.STATUS_ABORTADO
                execucao.data_fim = timezone.now()
                execucao.save(update_fields=["status", "data_fim"])
                messages.warning(request, f"Processo {execucao.pid} já havia finalizado. Execução marcada como abortada.")
                return redirect("cctdashboard:detalhe_execucao", pk=pk)
        except Exception as e:
            messages.error(request, f"Erro ao tentar abortar: {e}")
    else:
        messages.info(request, "Execução marcada para abortar. O processo será encerrado no próximo ciclo de verificação.")

    return redirect("cctdashboard:detalhe_execucao", pk=pk)


@login_required
def detalhe_execucao(request, pk):
    """Exibe detalhes e logs de uma execução do scraper."""
    execucao = get_object_or_404(ExecucaoScraper, pk=pk)
    context = {
        "execucao": execucao,
    }
    return render(request, "cctdashboard/detalhe_execucao.html", context)


@login_required
@require_POST
def limpar_execucoes(request):
    """Limpa execuções do scraper conforme opção selecionada."""
    opcao = request.POST.get("opcao", "concluidas")

    if opcao == "todas":
        queryset = ExecucaoScraper.objects.all()
        descricao = "todas as execuções"
    elif opcao == "concluidas":
        queryset = ExecucaoScraper.objects.filter(status=ExecucaoScraper.STATUS_CONCLUIDO)
        descricao = "execuções concluídas"
    elif opcao == "erro_abortado":
        queryset = ExecucaoScraper.objects.filter(
            status__in=[ExecucaoScraper.STATUS_ERRO, ExecucaoScraper.STATUS_ABORTADO]
        )
        descricao = "execuções com erro ou abortadas"
    elif opcao == "mantem_andamento":
        queryset = ExecucaoScraper.objects.exclude(status=ExecucaoScraper.STATUS_EM_ANDAMENTO)
        descricao = "execuções finalizadas (mantendo as em andamento)"
    else:
        messages.warning(request, "Opção de limpeza inválida.")
        return redirect("cctdashboard:execucoes_scraper")

    total = queryset.count()
    if total == 0:
        messages.info(request, "Nenhuma execução encontrada para limpar.")
        return redirect("cctdashboard:execucoes_scraper")

    queryset.delete()
    messages.success(request, f"Painel limpo com sucesso! {total} {descricao} foram removidas.")
    return redirect("cctdashboard:execucoes_scraper")


@login_required
def excluir_documento(request, pk):
    documento = get_object_or_404(DocumentoCCT, pk=pk)
    if request.method == "POST":
        documento.delete()
        messages.success(request, "Documento excluído com sucesso.")
        return redirect("cctdashboard:lista_documentos")
    return render(request, "cctdashboard/confirmar_exclusao.html", {
        "objeto": documento,
        "tipo": "documento",
        "voltar_url": "cctdashboard:detalhe_documento",
        "voltar_pk": pk,
    })


@login_required
@require_POST
def desativar_documento(request, pk):
    documento = get_object_or_404(DocumentoCCT, pk=pk)
    documento.ativo = False
    documento.save(update_fields=["ativo"])
    messages.success(request, "Documento marcado como 'não utilizar'. Ele não aparecerá mais nas listas principais.")
    return redirect("cctdashboard:detalhe_documento", pk=pk)


@login_required
@require_POST
def reativar_documento(request, pk):
    documento = get_object_or_404(DocumentoCCT, pk=pk)
    documento.ativo = True
    documento.save(update_fields=["ativo"])
    messages.success(request, "Documento reativado com sucesso.")
    return redirect("cctdashboard:detalhe_documento", pk=pk)


@login_required
def documentos_expirados(request):
    """Lista documentos CCT cuja data fim de vigência já passou."""
    from datetime import date
    hoje = date.today()
    queryset = DocumentoCCT.objects.select_related("sindicato").filter(
        ativo=True,
        data_fim_vigencia__lt=hoje,
    ).order_by("-data_fim_vigencia")

    tipo = request.GET.get("tipo", "").strip()
    sindicato_id = request.GET.get("sindicato", "").strip()
    q = request.GET.get("q", "").strip()

    if tipo:
        queryset = queryset.filter(tipo=tipo)
    if sindicato_id:
        queryset = queryset.filter(sindicato_id=sindicato_id)
    if q:
        queryset = queryset.filter(
            Q(sindicato__nome__icontains=q)
            | Q(sindicato__codigo__icontains=q)
        )

    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    sindicatos = Sindicato.objects.order_by("nome")
    context = {
        "page_obj": page_obj,
        "tipo": tipo,
        "sindicato_id": sindicato_id,
        "q": q,
        "sindicatos": sindicatos,
        "hoje": hoje,
    }
    return render(request, "cctdashboard/documentos_expirados.html", context)


# ============================================================
# FILTRO DE EMPRESAS POR SINDICATO + RELATÓRIO PDF
# ============================================================

@login_required
def filtrar_empresas_por_sindicato(request):
    sindicatos = Sindicato.objects.order_by("nome")
    sindicato_id = request.GET.get("sindicato", "").strip()
    empresas = []
    sindicato_selecionado = None

    if sindicato_id:
        sindicato_selecionado = get_object_or_404(Sindicato, pk=sindicato_id)
        empresas = (
            Empresa.objects.filter(sindicatos__sindicato=sindicato_selecionado)
            .distinct()
            .order_by("nome")
        )

    context = {
        "sindicatos": sindicatos,
        "sindicato_selecionado": sindicato_selecionado,
        "empresas": empresas,
        "sindicato_id": sindicato_id,
        "total_empresas": len(empresas),
    }
    return render(request, "cctdashboard/filtro_empresas_sindicato.html", context)


@login_required
def relatorio_empresas_sindicato_pdf(request):
    """Gera PDF com as empresas vinculadas ao sindicato selecionado."""
    from xhtml2pdf import pisa
    from django.template.loader import render_to_string

    sindicato_id = request.GET.get("sindicato", "").strip()
    if not sindicato_id:
        messages.error(request, "Selecione um sindicato para gerar o relatório.")
        return redirect("cctdashboard:filtro_empresas_por_sindicato")

    sindicato = get_object_or_404(Sindicato, pk=sindicato_id)
    empresas = (
        Empresa.objects.filter(sindicatos__sindicato=sindicato)
        .distinct()
        .order_by("nome")
    )

    html_string = render_to_string("cctdashboard/relatorio_empresas_pdf.html", {
        "sindicato": sindicato,
        "empresas": empresas,
        "total_empresas": empresas.count(),
        "data_geracao": timezone.now().strftime("%d/%m/%Y %H:%M:%S"),
    })

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="relatorio_empresas_{sindicato.codigo}.pdf"'
    pisa.CreatePDF(html_string, dest=response)
    return response


# ============================================================
# RELATÓRIO PROFISSIONAL DE CONTRIBUIÇÕES
# ============================================================

MESES_RELATORIO = {
    1: ("janeiro", "jan"), 2: ("fevereiro", "fev"), 3: ("março", "mar"),
    4: ("abril", "abr"), 5: ("maio", "mai"), 6: ("junho", "jun"),
    7: ("julho", "jul"), 8: ("agosto", "ago"), 9: ("setembro", "set"),
    10: ("outubro", "out"), 11: ("novembro", "nov"), 12: ("dezembro", "dez"),
}


def _normalizar_mes_relatorio(texto):
    valor = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", valor).strip()


def _meses_do_desconto(texto):
    """Converte texto extraído (MAR, março, 12x ao ano) em meses 1..12."""
    texto = _normalizar_mes_relatorio(texto)
    if not texto:
        return set()
    if re.search(r"\b(?:12\s*x|12\s*vezes|mensalmente|todos\s+os\s+meses|cada\s+mes)\b", texto):
        return set(range(1, 13))
    encontrados = set()
    for numero, nomes in MESES_RELATORIO.items():
        for nome in nomes:
            nome_normalizado = _normalizar_mes_relatorio(nome)
            if re.search(rf"\b{re.escape(nome_normalizado)}(?:o|es)?\b", texto):
                encontrados.add(numero)
    return encontrados


@login_required
def filtro_relatorio_contribuicoes(request):
    sindicatos = Sindicato.objects.order_by("nome")
    sindicato_id = request.GET.get("sindicato", "").strip()
    tipo = request.GET.get("tipo", "todas").strip()
    empresa_id = request.GET.get("empresa", "").strip()
    mes = request.GET.get("mes", "").strip()
    sindicatos_ids = [sindicato_id] if sindicato_id.isdigit() else []
    empresas = Empresa.objects.filter(sindicatos__sindicato_id__in=sindicatos_ids).distinct().order_by("nome") if sindicatos_ids else Empresa.objects.none()
    return render(request, "cctdashboard/filtro_relatorio_contribuicoes.html", {
        "sindicatos": sindicatos, "empresas": empresas, "sindicato_id": sindicato_id,
        "empresa_id": empresa_id, "tipo": tipo, "mes": mes, "meses_relatorio": MESES_RELATORIO,
    })


@login_required
def relatorio_contribuicoes_pdf(request):
    """Emite PDF filtrável pelo mês em que ocorre o desconto."""
    from xhtml2pdf import pisa
    from django.template.loader import render_to_string

    sindicato_id = request.GET.get("sindicato", "").strip()
    tipo = request.GET.get("tipo", "todas").strip()
    empresa_id = request.GET.get("empresa", "").strip()
    mes = request.GET.get("mes", "").strip()
    if not sindicato_id or not sindicato_id.isdigit():
        messages.error(request, "Selecione um sindicato válido para gerar o relatório.")
        return redirect("cctdashboard:filtro_relatorio_contribuicoes")
    sindicato = get_object_or_404(Sindicato, pk=int(sindicato_id))
    empresas = Empresa.objects.filter(sindicatos__sindicato=sindicato, ativo=True).distinct().order_by("nome")
    if empresa_id.isdigit():
        empresas = empresas.filter(pk=empresa_id)
    documentos = list(DocumentoCCT.objects.filter(sindicato=sindicato, ativo=True).order_by("-data_inicio_vigencia"))
    if tipo == "empregado":
        documentos = [d for d in documentos if d.contribuicao_sindical_empregado is not None or d.trecho_contribuicao_empregado]
    elif tipo == "patronal":
        documentos = [d for d in documentos if d.contribuicao_sindical_patronal is not None or d.trecho_contribuicao_patronal]
    mes_numero = int(mes) if mes.isdigit() and 1 <= int(mes) <= 12 else None
    if mes_numero:
        documentos = [d for d in documentos if mes_numero in _meses_do_desconto(d.contribuicao_sindical_empregado_meses)]
    # Monta estrutura por documento
    documento_padrao = None
    if len(documentos) > 1:
        documentos_com_linhas = []
        for doc in documentos:
            linhas_doc = [{"empresa": e, "documento": doc} for e in empresas]
            documentos_com_linhas.append({"documento": doc, "linhas": linhas_doc})
    else:
        documento_padrao = documentos[0] if documentos else None
        linhas = []
        for empresa in empresas:
            documento = documento_padrao
            if (empresa.convencao_aplicada_id and empresa.sindicato_aplicado_id == sindicato.pk
                    and empresa.convencao_aplicada and empresa.convencao_aplicada.ativo):
                documento = empresa.convencao_aplicada
            linhas.append({"empresa": empresa, "documento": documento})
        documentos_com_linhas = [{"documento": documento_padrao, "linhas": linhas}]
    html_string = render_to_string("cctdashboard/relatorio_contribuicoes_pdf.html", {
        "sindicato": sindicato, "empresas": empresas, "documentos": documentos,
        "documento": documento_padrao if len(documentos) <= 1 else None,
        "documentos_com_linhas": documentos_com_linhas, "tipo": tipo, "mes": mes_numero,
        "mes_nome": MESES_RELATORIO.get(mes_numero, ("",))[0] if mes_numero else "Todos",
        "data_geracao": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
    })
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="relatorio_contribuicoes_{sindicato.codigo}.pdf"'
    resultado = pisa.CreatePDF(html_string, dest=response)
    if resultado.err:
        return HttpResponse(b"Nao foi possivel gerar o PDF.", content_type="text/plain", status=500)
    return response


@login_required
def filtro_relatorio_desconto_mensal(request):
    mes = request.GET.get("mes", "").strip()
    return render(request, "cctdashboard/filtro_relatorio_desconto_mensal.html", {
        "mes": mes, "meses_relatorio": MESES_RELATORIO,
    })


@login_required
def relatorio_desconto_mensal_pdf(request):
    """Emite PDF com todos os sindicatos/documentos que têm desconto no mês selecionado."""
    from xhtml2pdf import pisa
    from django.template.loader import render_to_string

    mes = request.GET.get("mes", "").strip()
    if not mes.isdigit() or not 1 <= int(mes) <= 12:
        messages.error(request, "Selecione um mês válido (1-12) para gerar o relatório.")
        return redirect("cctdashboard:filtro_relatorio_desconto_mensal")
    mes_numero = int(mes)
    documentos = list(DocumentoCCT.objects.filter(ativo=True).order_by("sindicato__nome", "-data_inicio_vigencia"))
    documentos = [d for d in documentos if mes_numero in _meses_do_desconto(d.contribuicao_sindical_empregado_meses)]

    sindicatos_data = []
    for doc in documentos:
        sindicato = doc.sindicato
        empresas = Empresa.objects.filter(sindicatos__sindicato=sindicato, ativo=True).distinct().order_by("nome")
        sindicatos_data.append({
            "sindicato": sindicato,
            "documento": doc,
            "empresas": empresas,
        })

    html_string = render_to_string("cctdashboard/relatorio_desconto_mensal_pdf.html", {
        "sindicatos_data": sindicatos_data,
        "mes": mes_numero,
        "mes_nome": MESES_RELATORIO.get(mes_numero, ("",))[0],
        "data_geracao": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
    })
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="relatorio_desconto_mensal_{mes_numero:02d}.pdf"'
    resultado = pisa.CreatePDF(html_string, dest=response)
    if resultado.err:
        return HttpResponse(b"Nao foi possivel gerar o PDF.", content_type="text/plain", status=500)
    return response


# ============================================================
# AGENDAMENTO DO SCRAPER
# ============================================================

@login_required
def lista_agendamentos(request):
    agendamentos = AgendamentoScraper.objects.all()
    context = {
        "agendamentos": agendamentos,
    }
    return render(request, "cctdashboard/lista_agendamentos.html", context)


@login_required
def criar_agendamento(request):
    if request.method == "POST":
        horario = request.POST.get("horario", "").strip()
        recorrencia = request.POST.get("recorrencia", "DIARIA").strip()
        dia_semana = request.POST.get("dia_semana", "").strip() or None
        dia_mes = request.POST.get("dia_mes", "").strip() or None
        headless = request.POST.get("headless") == "on"
        forcar = request.POST.get("forcar") == "on"
        sindicato_codigo = request.POST.get("sindicato_codigo", "").strip()

        if not horario:
            messages.error(request, "Informe o horário.")
            return render(request, "cctdashboard/form_agendamento.html", {"sindicatos": Sindicato.objects.order_by("nome")})

        try:
            from datetime import datetime
            horario_obj = datetime.strptime(horario, "%H:%M").time()
        except ValueError:
            messages.error(request, "Horário inválido. Use o formato HH:MM.")
            return render(request, "cctdashboard/form_agendamento.html", {"sindicatos": Sindicato.objects.order_by("nome")})

        try:
            dia_semana_int = int(dia_semana) if dia_semana is not None else None
            dia_mes_int = int(dia_mes) if dia_mes is not None else None
        except ValueError:
            messages.error(request, "Dia da semana ou do mês inválido.")
            return render(request, "cctdashboard/form_agendamento.html", {"sindicatos": Sindicato.objects.order_by("nome")})
        if recorrencia == AgendamentoScraper.RECORRENCIA_SEMANAL and dia_semana_int not in range(7):
            messages.error(request, "Selecione um dia da semana válido.")
            return render(request, "cctdashboard/form_agendamento.html", {"sindicatos": Sindicato.objects.order_by("nome")})
        if recorrencia == AgendamentoScraper.RECORRENCIA_MENSAL and dia_mes_int not in range(1, 32):
            messages.error(request, "O dia do mês deve estar entre 1 e 31.")
            return render(request, "cctdashboard/form_agendamento.html", {"sindicatos": Sindicato.objects.order_by("nome")})
        if recorrencia != AgendamentoScraper.RECORRENCIA_SEMANAL:
            dia_semana_int = None
        if recorrencia != AgendamentoScraper.RECORRENCIA_MENSAL:
            dia_mes_int = None

        AgendamentoScraper.objects.create(
            horario=horario_obj,
            recorrencia=recorrencia,
            dia_semana=dia_semana_int,
            dia_mes=dia_mes_int,
            headless=headless,
            forcar=forcar,
            sindicato_codigo=sindicato_codigo,
            ativo=True,
        )
        messages.success(request, "Agendamento criado com sucesso!")
        return redirect("cctdashboard:lista_agendamentos")

    context = {
        "sindicatos": Sindicato.objects.order_by("nome"),
        "titulo": "Novo Agendamento",
    }
    return render(request, "cctdashboard/form_agendamento.html", context)


@login_required
def editar_agendamento(request, pk):
    agendamento = get_object_or_404(AgendamentoScraper, pk=pk)
    if request.method == "POST":
        horario = request.POST.get("horario", "").strip()
        recorrencia = request.POST.get("recorrencia", "DIARIA").strip()
        dia_semana = request.POST.get("dia_semana", "").strip() or None
        dia_mes = request.POST.get("dia_mes", "").strip() or None
        headless = request.POST.get("headless") == "on"
        forcar = request.POST.get("forcar") == "on"
        sindicato_codigo = request.POST.get("sindicato_codigo", "").strip()
        ativo = request.POST.get("ativo") == "on"

        if not horario:
            messages.error(request, "Informe o horário.")
            return render(request, "cctdashboard/form_agendamento.html", {"agendamento": agendamento, "sindicatos": Sindicato.objects.order_by("nome")})

        try:
            from datetime import datetime
            horario_obj = datetime.strptime(horario, "%H:%M").time()
        except ValueError:
            messages.error(request, "Horário inválido. Use o formato HH:MM.")
            return render(request, "cctdashboard/form_agendamento.html", {"agendamento": agendamento, "sindicatos": Sindicato.objects.order_by("nome")})

        agendamento.horario = horario_obj
        agendamento.recorrencia = recorrencia
        agendamento.dia_semana = int(dia_semana) if dia_semana is not None else None
        agendamento.dia_mes = int(dia_mes) if dia_mes is not None else None
        agendamento.headless = headless
        agendamento.forcar = forcar
        agendamento.sindicato_codigo = sindicato_codigo
        agendamento.ativo = ativo
        agendamento.save()

        messages.success(request, "Agendamento atualizado com sucesso!")
        return redirect("cctdashboard:lista_agendamentos")

    context = {
        "agendamento": agendamento,
        "sindicatos": Sindicato.objects.order_by("nome"),
        "titulo": "Editar Agendamento",
    }
    return render(request, "cctdashboard/form_agendamento.html", context)


@login_required
@require_POST
def excluir_agendamento(request, pk):
    agendamento = get_object_or_404(AgendamentoScraper, pk=pk)
    agendamento.delete()
    messages.success(request, "Agendamento excluído com sucesso.")
    return redirect("cctdashboard:lista_agendamentos")


# ============================================================
# ATUALIZAR VIGENCIAS DE DOCUMENTOS EXISTENTES
# ============================================================

import threading

# ============================================================
# ANALISAR CCTs (visão unificada de datas + dados complementares)
# ============================================================

# Estado global unificado para acompanhar execução em segundo plano
_estado_analisar = {
    "rodando": False,
    "total": 0,
    "atual": 0,
    "mensagens": [],
    "atualizados": 0,
    "sem_mudanca": 0,
    "erros": 0,
    "erro_pdf": 0,
}


def _thread_analisar_ccts(sindicato_codigo, modo, apenas_vazios, limite, modo_ocr="auto"):
    """Executa a análise de CCTs em segundo plano.

    ``modo`` controla o escopo da reanálise:
      - "datas"       : apenas vigência / data de registro MTE
      - "completo"    : datas + dados complementares (data_base, reajuste,
                        contribuições, trechos)
      - "completo_ia" : completo + reset do status_analise_ia para PENDENTE

    ``apenas_vazios`` filtra documentos que ainda não possuem
    data_fim_vigencia ou data_registro_mte (somente no modo "datas").
    """
    global _estado_analisar
    _estado_analisar["rodando"] = True
    _estado_analisar["mensagens"] = []
    _estado_analisar["atualizados"] = 0
    _estado_analisar["sem_mudanca"] = 0
    _estado_analisar["erros"] = 0
    _estado_analisar["erro_pdf"] = 0

    queryset = DocumentoCCT.objects.filter(ativo=True).exclude(
        arquivo_pdf=""
    ).exclude(arquivo_pdf__isnull=True)

    if sindicato_codigo:
        queryset = queryset.filter(sindicato__codigo=sindicato_codigo)

    if apenas_vazios and modo == "datas":
        queryset = queryset.filter(
            data_fim_vigencia__isnull=True
        ) | queryset.filter(data_registro_mte__isnull=True)

    total = queryset.count()
    if limite and limite > 0:
        queryset = queryset[:limite]
        total = min(total, limite)

    _estado_analisar["total"] = total
    _estado_analisar["atual"] = 0

    for idx, doc in enumerate(queryset, start=1):
        if not _estado_analisar["rodando"]:
            _estado_analisar["mensagens"].append("[PARADO] Execução interrompida pelo usuário.")
            break

        _estado_analisar["atual"] = idx
        _estado_analisar["mensagens"].append(
            f"[{idx}/{total}] #{doc.pk} — {doc.sindicato} — {doc.tipo}"
        )

        caminho_pdf = doc.arquivo_pdf
        if not os.path.isabs(caminho_pdf):
            caminho_pdf = str(Path(settings.BASE_DIR) / caminho_pdf)

        if not os.path.exists(caminho_pdf):
            _estado_analisar["mensagens"].append(
                f"  [AVISO] PDF não encontrado: {caminho_pdf}"
            )
            _estado_analisar["erros"] += 1
            continue

        if modo_ocr == "somente" and extrair_texto_pdf(caminho_pdf, max_paginas=3).strip():
            _estado_analisar["mensagens"].append("  [OCR] Ignorado: PDF já possui texto nativo.")
            continue
        try:
            caminho_ocr = garantir_ocr_pdf(caminho_pdf, modo="sempre" if modo_ocr in ("sempre", "somente") else "auto")
            if caminho_ocr != caminho_pdf:
                _estado_analisar["mensagens"].append(f"  [OCR] PDF pesquisável gerado: {os.path.basename(caminho_ocr)}")
                caminho_pdf = caminho_ocr
        except Exception as exc_ocr:
            _estado_analisar["mensagens"].append(f"  [AVISO] OCR não executado: {exc_ocr}")

        texto = extrair_texto_pdf(caminho_pdf)
        if not texto or texto.startswith("[ERRO"):
            _estado_analisar["erro_pdf"] += 1
            _estado_analisar["erros"] += 1
            _estado_analisar["mensagens"].append(
                f"  [ERRO] Falha ao extrair texto do PDF."
            )
            continue

        if modo == "datas":
            # Importa do management command para reaproveitar regex
            from cctcore.management.commands.atualizar_vigencias import extrair_datas_do_texto
            datas = extrair_datas_do_texto(texto)
            compl = None
        else:
            from cctcore.management.commands.atualizar_vigencias import (
                extrair_datas_do_texto,
                extrair_dados_complementares_do_texto,
            )
            datas = extrair_datas_do_texto(texto)
            compl = extrair_dados_complementares_do_texto(texto)

        encontrado = []
        if datas["data_inicio"]:
            encontrado.append(f"início={datas['data_inicio']}")
        if datas["data_fim"]:
            encontrado.append(f"fim={datas['data_fim']}")
        if datas["data_registro_mte"]:
            encontrado.append(f"registro_mte={datas['data_registro_mte']}")

        if encontrado:
            _estado_analisar["mensagens"].append(
                f"  Encontrado: {', '.join(encontrado)}"
            )
        else:
            _estado_analisar["mensagens"].append(
                f"  [AVISO] Nenhuma data encontrada no texto."
            )

        mudou = False
        campos_atualizar = []

        if datas["data_inicio"] and doc.data_inicio_vigencia != datas["data_inicio"]:
            doc.data_inicio_vigencia = datas["data_inicio"]
            campos_atualizar.append("data_inicio_vigencia")
            mudou = True

        if datas["data_fim"] and doc.data_fim_vigencia != datas["data_fim"]:
            doc.data_fim_vigencia = datas["data_fim"]
            campos_atualizar.append("data_fim_vigencia")
            mudou = True

        if datas["data_registro_mte"] and doc.data_registro_mte != datas["data_registro_mte"]:
            doc.data_registro_mte = datas["data_registro_mte"]
            campos_atualizar.append("data_registro_mte")
            mudou = True

        if compl is not None:
            if compl["data_base"] and doc.data_base != compl["data_base"]:
                doc.data_base = compl["data_base"]
                campos_atualizar.append("data_base")
                mudou = True

            if compl["reajuste_percentual"] is not None:
                from decimal import Decimal
                novo_valor = Decimal(str(compl["reajuste_percentual"]))
                if doc.reajuste_percentual != novo_valor:
                    doc.reajuste_percentual = novo_valor
                    campos_atualizar.append("reajuste_percentual")
                    mudou = True

            if compl["contribuicao_sindical_empregado"] is not None:
                from decimal import Decimal
                novo_valor = Decimal(str(compl["contribuicao_sindical_empregado"]))
                if doc.contribuicao_sindical_empregado != novo_valor:
                    doc.contribuicao_sindical_empregado = novo_valor
                    campos_atualizar.append("contribuicao_sindical_empregado")
                    mudou = True

            if compl["contribuicao_sindical_patronal"] is not None:
                from decimal import Decimal
                novo_valor = Decimal(str(compl["contribuicao_sindical_patronal"]))
                if doc.contribuicao_sindical_patronal != novo_valor:
                    doc.contribuicao_sindical_patronal = novo_valor
                    campos_atualizar.append("contribuicao_sindical_patronal")
                    mudou = True

            if compl["trecho_contribuicao_empregado"] is not None:
                if doc.trecho_contribuicao_empregado != compl["trecho_contribuicao_empregado"]:
                    doc.trecho_contribuicao_empregado = compl["trecho_contribuicao_empregado"]
                    campos_atualizar.append("trecho_contribuicao_empregado")
                    mudou = True

            if compl["trecho_contribuicao_patronal"] is not None:
                if doc.trecho_contribuicao_patronal != compl["trecho_contribuicao_patronal"]:
                    doc.trecho_contribuicao_patronal = compl["trecho_contribuicao_patronal"]
                    campos_atualizar.append("trecho_contribuicao_patronal")
                    mudou = True

            if compl["contribuicao_sindical_empregado_meses"] is not None:
                if doc.contribuicao_sindical_empregado_meses != compl["contribuicao_sindical_empregado_meses"]:
                    doc.contribuicao_sindical_empregado_meses = compl["contribuicao_sindical_empregado_meses"]
                    campos_atualizar.append("contribuicao_sindical_empregado_meses")
                    mudou = True

        if modo == "completo_ia":
            doc.status_analise_ia = DocumentoCCT.STATUS_ANALISE_PENDENTE
            if "status_analise_ia" not in campos_atualizar:
                campos_atualizar.append("status_analise_ia")
            mudou = True

        if mudou:
            doc.save(update_fields=campos_atualizar)
            _estado_analisar["atualizados"] += 1
            _estado_analisar["mensagens"].append(
                f"  [OK] Atualizado: {', '.join(campos_atualizar)}"
            )
        else:
            _estado_analisar["sem_mudanca"] += 1

    _estado_analisar["rodando"] = False


@login_required
def analisar_ccts(request):
    """Página unificada para analisar CCTs (datas e/ou dados complementares)."""
    global _estado_analisar

    if request.method == "POST":
        acao = request.POST.get("acao", "")

        if acao == "iniciar":
            if _estado_analisar["rodando"]:
                messages.warning(request, "Já há uma execução em andamento.")
                return redirect("cctdashboard:analisar_ccts")

            sindicato_codigo = request.POST.get("sindicato_codigo", "").strip()
            modo = request.POST.get("modo", "datas").strip()
            if modo not in ("datas", "completo", "completo_ia"):
                modo = "datas"
            apenas_vazios = request.POST.get("apenas_vazios") == "on"
            limite_str = request.POST.get("limite", "0").strip()
            try:
                limite = int(limite_str)
            except ValueError:
                limite = 0

            modo_ocr = request.POST.get("modo_ocr", "auto").strip()
            if modo_ocr not in ("auto", "sempre", "somente"):
                modo_ocr = "auto"
            t = threading.Thread(
                target=_thread_analisar_ccts,
                args=(sindicato_codigo, modo, apenas_vazios, limite, modo_ocr),
                daemon=True,
            )
            t.start()

            messages.success(request, "Análise de CCTs iniciada em segundo plano.")
            return redirect("cctdashboard:analisar_ccts")

        elif acao == "parar":
            # Não conseguimos matar a thread de forma segura,
            # mas podemos marcar para parar no próximo ciclo
            _estado_analisar["rodando"] = False
            messages.info(request, "Sinal de parada enviado. A execução terminará no próximo documento.")
            return redirect("cctdashboard:analisar_ccts")

    # Contagens para os cards
    total_docs = DocumentoCCT.objects.filter(ativo=True).count()
    com_pdf = (
        DocumentoCCT.objects.filter(ativo=True)
        .exclude(arquivo_pdf="")
        .exclude(arquivo_pdf__isnull=True)
        .count()
    )
    sem_data_fim = DocumentoCCT.objects.filter(ativo=True, data_fim_vigencia__isnull=True).count()
    sem_trecho = (
        DocumentoCCT.objects.filter(ativo=True)
        .filter(Q(trecho_contribuicao_empregado__isnull=True) | Q(trecho_contribuicao_empregado=""))
        .count()
    )

    context = {
        "titulo": "Analisar CCTs",
        "estado": _estado_analisar,
        "total_docs": total_docs,
        "com_pdf": com_pdf,
        "sem_data_fim": sem_data_fim,
        "sem_trecho": sem_trecho,
        "sindicatos": Sindicato.objects.order_by("nome"),
    }
    return render(request, "cctdashboard/analisar_ccts.html", context)


@login_required
def atualizar_vigencias(request):
    """Redireciona para a página unificada de análise de CCTs (compatibilidade)."""
    return redirect("cctdashboard:analisar_ccts")


@login_required
def reanalisar_disponiveis(request):
    """Redireciona para a página unificada de análise de CCTs (compatibilidade)."""
    return redirect("cctdashboard:analisar_ccts")
