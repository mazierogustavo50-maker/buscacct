from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import FileResponse, Http404
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
import json

from cctcore.models import Sindicato, Empresa, EmpresaSindicato, DocumentoCCT
from cctbuscador.models import ExecucaoScraper
from .forms import SindicatoForm, EmpresaForm, ImportarSindicatosForm, ImportarEmpresasForm
from cctcore.services import extrair_texto_pdf, analisar_cct_com_ia


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
        nao_encontrados = ultima_execucao.nao_encontrados_json

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
def lista_sindicatos(request):
    queryset = Sindicato.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(nome__icontains=q) | Q(codigo__icontains=q) | Q(cnpj__icontains=q)
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
    queryset = Empresa.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(nome__icontains=q) | Q(codigo__icontains=q)
        )

    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "q": q,
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

    context = {
        "empresa": empresa,
        "sindicatos": sindicatos,
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
    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
    }
    return render(request, "cctdashboard/execucoes_scraper.html", context)


@login_required
@require_POST
def executar_scraper(request):
    """Inicia o scraper em background via subprocess."""
    headless = request.POST.get("headless", "on") == "on"
    forcar = request.POST.get("forcar") == "on"
    sindicato_codigo = request.POST.get("sindicato_codigo", "").strip()

    manage_py = os.path.join(settings.BASE_DIR, "manage.py")
    cmd = [sys.executable, manage_py, "run_scraper"]
    if headless:
        cmd.append("--headless")
    if forcar:
        cmd.append("--forcar")
    if sindicato_codigo:
        cmd.extend(["--sindicato-codigo", sindicato_codigo])

    env = os.environ.copy()
    env.setdefault("DJANGO_SETTINGS_MODULE", "buscacct.settings")

    # Cria registro da execução antes de iniciar o subprocess
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
        messages.success(request, f"Scraper iniciado em background (PID {proc.pid}). Acompanhe na lista de execuções.")
    except Exception as e:
        execucao.status = ExecucaoScraper.STATUS_ERRO
        execucao.save(update_fields=["status"])
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
@require_POST
def analisar_documento_ia(request, pk):
    """Executa análise de CCT via IA (OpenCode Go)."""
    documento = get_object_or_404(DocumentoCCT, pk=pk)

    if not documento.arquivo_pdf:
        messages.error(request, "Documento não possui arquivo PDF para análise.")
        return redirect("cctdashboard:detalhe_documento", pk=pk)

    # Atualiza status
    documento.status_analise_ia = DocumentoCCT.STATUS_ANALISE_EM_ANDAMENTO
    documento.save(update_fields=["status_analise_ia"])

    try:
        texto = extrair_texto_pdf(documento.arquivo_pdf)
        if not texto or texto.startswith("[ERRO"):
            raise ValueError(texto or "Não foi possível extrair texto do PDF.")

        resultado = analisar_cct_com_ia(texto)

        if "erro" in resultado:
            documento.status_analise_ia = DocumentoCCT.STATUS_ANALISE_ERRO
            documento.analise_ia_texto = resultado["erro"]
            documento.save(update_fields=["status_analise_ia", "analise_ia_texto"])
            messages.error(request, f"Falha na análise: {resultado['erro']}")
        else:
            documento.status_analise_ia = DocumentoCCT.STATUS_ANALISE_CONCLUIDO
            documento.analise_ia_json = resultado.get("resultado")
            # Monta resumo textual para exibição rápida
            resumo = resultado.get("resultado", {}).get("resumo", "")
            documento.analise_ia_texto = json.dumps(resultado.get("resultado"), ensure_ascii=False, indent=2)
            documento.data_analise_ia = timezone.now()
            documento.save(update_fields=["status_analise_ia", "analise_ia_json", "analise_ia_texto", "data_analise_ia"])
            messages.success(request, "Análise com IA concluída com sucesso!")
    except Exception as e:
        documento.status_analise_ia = DocumentoCCT.STATUS_ANALISE_ERRO
        documento.analise_ia_texto = str(e)
        documento.save(update_fields=["status_analise_ia", "analise_ia_texto"])
        messages.error(request, f"Erro durante análise: {e}")

    return redirect("cctdashboard:detalhe_documento", pk=pk)
