from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import FileResponse, Http404
from django.conf import settings
from django.contrib.auth.decorators import login_required
from pathlib import Path

from cctcore.models import Sindicato, Empresa, EmpresaSindicato, DocumentoCCT
from cctbuscador.models import ExecucaoScraper


@login_required
def home(request):
    total_sindicatos = Sindicato.objects.count()
    total_empresas = Empresa.objects.count()
    total_documentos = DocumentoCCT.objects.count()
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

    context = {
        "total_sindicatos": total_sindicatos,
        "total_empresas": total_empresas,
        "total_documentos": total_documentos,
        "total_cct": total_cct,
        "total_ta_cct": total_ta_cct,
        "execucoes_recentes": execucoes_recentes,
        "documentos_por_tipo": documentos_por_tipo,
        "sindicato_labels": sindicato_labels,
        "sindicato_data": sindicato_data,
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
    documentos = sindicato.documentos.all()

    context = {
        "sindicato": sindicato,
        "empresas": empresas,
        "documentos": documentos,
    }
    return render(request, "cctdashboard/detalhe_sindicato.html", context)


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
def lista_documentos(request):
    queryset = DocumentoCCT.objects.select_related("sindicato").all()

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
def execucoes_scraper(request):
    queryset = ExecucaoScraper.objects.all()
    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
    }
    return render(request, "cctdashboard/execucoes_scraper.html", context)
