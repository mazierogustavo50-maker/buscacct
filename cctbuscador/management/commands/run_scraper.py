import os
import time
import re
import shutil
import signal
import unicodedata
import requests
import pandas as pd
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

# Flag global para sinal SIGTERM
_sinal_abortar = False


def _handler_sigterm(signum, frame):
    global _sinal_abortar
    _sinal_abortar = True

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from cctbuscador.models import ExecucaoScraper
from cctcore.models import Sindicato, DocumentoCCT

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


# ==========================================
# CONFIGURAÇÕES DE DIRETÓRIOS E ARQUIVOS
# ==========================================
BASE_DIR = settings.BASE_DIR
DOWNLOAD_DIR = os.path.join(BASE_DIR, "convencoes")
DOC_DIR = os.path.join(DOWNLOAD_DIR, "convencoesdoc")
EXCEL_FILE = os.path.join(BASE_DIR, "cnpjs.xlsx")
SINDICATO_SIS_FILE = os.path.join(BASE_DIR, "sindicatosistema.xlsx")
TEMP_DL_DIR = os.path.join(BASE_DIR, "temp_dl")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(DOC_DIR, exist_ok=True)
os.makedirs(TEMP_DL_DIR, exist_ok=True)


# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================
def limpar_cnpj(cnpj):
    s = str(cnpj)
    if s.endswith('.0'):
        s = s[:-2]
    return re.sub(r'[^0-9]', '', s).zfill(14)


def formatar_cnpj(cnpj_digits):
    c = cnpj_digits.zfill(14)
    return f"{c[0:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"


def formatar_nome_arquivo(tipo, sindicato, inicio_vigencia):
    nome = f"{tipo}-{sindicato}-{inicio_vigencia}"
    nome = re.sub(r'[\\/*?:"<>|]', "", nome)
    return nome[:200]


def normalizar_texto(texto):
    try:
        texto = str(texto)
        texto = unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode("utf-8")
        return re.sub(r'\s+', ' ', texto).upper().strip()
    except Exception:
        return str(texto).upper().strip()


_PADRAO_SIND_FED = re.compile(
    r'\b('
    r'SINDICATO|SIND\b|SINDI\b|SINTR|SINTEC|SINTRAF|SINTESP|SINDICAD|'
    r'FEDERAC|FEDERA|FED\b|FEDER\b|CONFEDERAC|CONFEDER|CONF\b|'
    r'CENTRAL|UNIAO|ASSOCIAC|ASSOCIA'
    r')', re.IGNORECASE
)

_PADRAO_EMPRESA = re.compile(
    r'\b('
    r'LTDA|S\.A\b|S/A\b|EIRELI|EPP\b|MEI\b|'
    r'(?<!\w)ME(?!\w)'
    r')', re.IGNORECASE
)


def e_sindicato_ou_federacao(texto_parte):
    t = normalizar_texto(texto_parte)
    tem_sind_fed = bool(_PADRAO_SIND_FED.search(t))
    tem_empresa = bool(_PADRAO_EMPRESA.search(t))
    if tem_sind_fed:
        return True
    if tem_empresa:
        return False
    return False


def aguardar_download(diretorio, timeout=40, abortar_check=None):
    inicio = time.time()
    while time.time() - inicio < timeout:
        if abortar_check and abortar_check():
            return "__ABORTADO__"
        arquivos = [f for f in os.listdir(diretorio)
                    if not f.endswith('.crdownload') and not f.endswith('.tmp')]
        if arquivos:
            time.sleep(2)
            return os.path.join(diretorio, arquivos[0])
        time.sleep(1)
    return None


def limpar_temp():
    for f in os.listdir(TEMP_DL_DIR):
        try:
            os.remove(os.path.join(TEMP_DL_DIR, f))
        except Exception:
            pass


def converter_para_pdf(caminho_doc):
    ext = os.path.splitext(caminho_doc)[1].lower()
    if ext not in ('.doc', '.docx'):
        return caminho_doc

    abs_doc = os.path.abspath(caminho_doc)
    nome_base = os.path.splitext(os.path.basename(caminho_doc))[0]
    abs_pdf = os.path.join(os.path.dirname(abs_doc), nome_base + '.pdf')
    destino_doc = os.path.join(DOC_DIR, os.path.basename(caminho_doc))

    os.makedirs(DOC_DIR, exist_ok=True)

    print(f"  Convertendo para PDF: {os.path.basename(caminho_doc)} ...")

    # Tentativa 1: Microsoft Word (Windows)
    try:
        import win32com.client
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        try:
            doc = word.Documents.Open(abs_doc)
            doc.SaveAs(abs_pdf, FileFormat=17)
            doc.Close(False)
            print(f"  [OK] PDF gerado via Word: {os.path.basename(abs_pdf)}")
            try:
                if os.path.exists(destino_doc):
                    os.remove(destino_doc)
                shutil.move(abs_doc, destino_doc)
                print(f"  [OK] .doc movido para convencoesdoc: {os.path.basename(destino_doc)}")
            except Exception as e_mv:
                print(f"  [AVISO] Nao foi possivel mover o .doc original: {e_mv}")
            return abs_pdf
        except Exception as e:
            print(f"  [ERRO] Falha ao converter via Word {os.path.basename(caminho_doc)}: {e}")
            return caminho_doc
        finally:
            try:
                word.Quit()
            except Exception:
                pass
    except ImportError:
        pass  # Fallback para LibreOffice
    except Exception as e:
        print(f"  [AVISO] Word indisponivel: {e}")

    # Tentativa 2: LibreOffice (Linux / Docker)
    try:
        import subprocess
        cmd = [
            "soffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", os.path.dirname(abs_doc),
            abs_doc
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and os.path.exists(abs_pdf):
            print(f"  [OK] PDF gerado via LibreOffice: {os.path.basename(abs_pdf)}")
            try:
                if os.path.exists(destino_doc):
                    os.remove(destino_doc)
                shutil.move(abs_doc, destino_doc)
                print(f"  [OK] .doc movido para convencoesdoc: {os.path.basename(destino_doc)}")
            except Exception as e_mv:
                print(f"  [AVISO] Nao foi possivel mover o .doc original: {e_mv}")
            return abs_pdf
        else:
            print(f"  [AVISO] LibreOffice nao conseguiu converter: {result.stderr or result.stdout}")
            return caminho_doc
    except Exception as e:
        print(f"  [AVISO] LibreOffice indisponivel: {e}")
        return caminho_doc


def configurar_driver(headless=False):
    options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": os.path.abspath(TEMP_DL_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
    }
    options.add_experimental_option("prefs", prefs)

    # Headless
    if headless:
        options.add_argument("--headless=new")

    # Flags anti-detecção
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Flags obrigatórias para rodar Chrome em container Docker
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    # Timeouts curtos para permitir abortamento rápido
    driver.set_page_load_timeout(15)
    driver.set_script_timeout(10)
    return driver


def parse_data_br(data_str):
    if not data_str:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(data_str, fmt).date()
        except ValueError:
            continue
    return None


# ==========================================
# MANAGEMENT COMMAND
# ==========================================

def baixar_arquivo_direto(driver, link_element, destino_path, log_func=None):
    """
    Baixa o arquivo diretamente via requests usando os cookies da sessão Selenium.
    Evita abrir nova janela/popup e salva diretamente no destino final.
    Retorna True se conseguiu, False caso contrário.
    """
    try:
        href = link_element.get_attribute("href")
        if not href or href.strip() in ("", "#", "javascript:void(0)"):
            # Tenta extrair onclick ou data attribute
            onclick = link_element.get_attribute("onclick") or ""
            m = re.search(r"window\.open\(['\"](.+?)['\"]", onclick)
            if m:
                href = m.group(1)
            else:
                if log_func:
                    log_func("  [AVISO] Link sem href válido, tentando fluxo legado...")
                return False

        # Resolve URL relativo
        base_url = driver.current_url
        if href.startswith("/"):
            from urllib.parse import urljoin
            href = urljoin(base_url, href)

        # Monta cookies da sessão Selenium
        cookies = driver.get_cookies()
        session = requests.Session()
        for c in cookies:
            session.cookies.set(c["name"], c["value"])

        headers = {
            "User-Agent": driver.execute_script("return navigator.userAgent;"),
            "Accept": "application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,*/*",
        }

        if log_func:
            log_func(f"  [DOWNLOAD DIRETO] Baixando: {href[:100]}...")

        resp = session.get(href, headers=headers, timeout=60, allow_redirects=True)
        resp.raise_for_status()

        # Determina extensão pelo Content-Type ou URL
        content_type = resp.headers.get("Content-Type", "").lower()
        if "pdf" in content_type:
            ext = ".pdf"
        elif "word" in content_type or "officedocument" in content_type:
            ext = ".docx"
        elif "msword" in content_type:
            ext = ".doc"
        else:
            # Tenta pela URL
            if ".pdf" in href.lower():
                ext = ".pdf"
            elif ".docx" in href.lower():
                ext = ".docx"
            elif ".doc" in href.lower():
                ext = ".doc"
            else:
                ext = ".pdf"  # fallback

        # Garante que o destino tenha a extensão correta
        destino_com_ext = os.path.splitext(destino_path)[0] + ext
        os.makedirs(os.path.dirname(destino_com_ext), exist_ok=True)

        with open(destino_com_ext, "wb") as f:
            f.write(resp.content)

        if log_func:
            log_func(f"  [OK] Download direto concluído: {os.path.basename(destino_com_ext)} ({len(resp.content)} bytes)")
        return destino_com_ext

    except Exception as e:
        if log_func:
            log_func(f"  [AVISO] Download direto falhou: {e}. Tentando fluxo legado...")
        return False


class Command(BaseCommand):
    help = "Executa o scraper do Mediador MTE e registra documentos no banco."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sindicato-codigo",
            type=str,
            help="Código do sindicato para buscar apenas um sindicato.",
        )
        parser.add_argument(
            "--headless",
            action="store_true",
            help="Executa o Chrome em modo headless.",
        )
        parser.add_argument(
            "--execucao-id",
            type=int,
            help="ID da execução existente (usado pela interface web).",
        )
        parser.add_argument(
            "--forcar",
            action="store_true",
            help="Força o re-download mesmo se o arquivo já existir no disco ou no banco.",
        )

    def log(self, msg):
        self.stdout.write(msg)
        self.linhas_log.append(msg)

    def _verificar_abortar(self, execucao):
        """Verifica se a execução foi marcada para abortar (banco ou sinal)."""
        global _sinal_abortar
        if _sinal_abortar:
            return True
        try:
            execucao.refresh_from_db(fields=["abortar"])
            return execucao.abortar
        except Exception:
            return False

    def _salvar_progresso(self, execucao):
        """Persiste log e contadores no banco para acompanhamento em tempo real."""
        try:
            execucao.log_texto = "\n".join(self.linhas_log)
            execucao.nao_encontrados_json = self.rel_nao_encontrados
            execucao.save(update_fields=["log_texto", "total_baixados", "total_ja_existentes", "total_nao_encontrados", "nao_encontrados_json"])
        except Exception as e:
            self.stdout.write(f"[AVISO] Falha ao salvar progresso: {e}")

    def handle(self, *args, **options):
        self.linhas_log = []
        # Registra handler de SIGTERM para capturar sinal da view web
        signal.signal(signal.SIGTERM, _handler_sigterm)
        execucao_id = options.get("execucao_id")

        if execucao_id:
            try:
                execucao = ExecucaoScraper.objects.get(pk=execucao_id)
                execucao.status = ExecucaoScraper.STATUS_EM_ANDAMENTO
                execucao.abortar = False
                execucao.save(update_fields=["status", "abortar"])
            except ExecucaoScraper.DoesNotExist:
                self.stdout.write(f"[ERRO] Execução {execucao_id} não encontrada.")
                return
        else:
            execucao = ExecucaoScraper.objects.create(status=ExecucaoScraper.STATUS_EM_ANDAMENTO)

        headless = options.get("headless", False)
        sindicato_codigo = options.get("sindicato_codigo")
        forcar = options.get("forcar", False)

        try:
            self.processar(sindicato_codigo, headless, execucao, forcar)
            if execucao.status == ExecucaoScraper.STATUS_EM_ANDAMENTO:
                execucao.status = ExecucaoScraper.STATUS_CONCLUIDO
        except Exception as e:
            self.log(f"[ERRO FATAL] {e}")
            if execucao.status == ExecucaoScraper.STATUS_EM_ANDAMENTO:
                execucao.status = ExecucaoScraper.STATUS_ERRO
            import traceback
            self.log(traceback.format_exc())
        finally:
            execucao.data_fim = timezone.now()
            execucao.log_texto = "\n".join(self.linhas_log)
            execucao.save()

        self.log(f"\nExecução {execucao.id} finalizada: {execucao.get_status_display()}")

    def processar(self, sindicato_codigo, headless, execucao, forcar=False):
        # 1. Buscar sindicatos do banco de dados
        sindicatos = Sindicato.objects.all()
        if sindicato_codigo:
            sindicatos = sindicatos.filter(codigo=sindicato_codigo)
            if not sindicatos.exists():
                self.log(f"[AVISO] Nenhum sindicato encontrado com código '{sindicato_codigo}'.")
                return
            self.log(f"Filtrado por sindicato '{sindicato_codigo}': {sindicatos.count()} registro(s).")
        else:
            self.log(f"Sindicatos carregados do banco: {sindicatos.count()} registro(s).")

        # 1b. Carregar tabela de códigos (fallback opcional)
        mapa_codigo = {}
        try:
            df_sis = pd.read_excel(SINDICATO_SIS_FILE)
            col_sis_cnpj = next((c for c in df_sis.columns if 'cnpj' in str(c).lower()), None)
            col_sis_codigo = next((c for c in df_sis.columns if 'codigo' in str(c).lower()), None)
            if col_sis_cnpj and col_sis_codigo:
                for _, r in df_sis.iterrows():
                    k = limpar_cnpj(r[col_sis_cnpj])
                    v = str(r[col_sis_codigo]).strip()
                    mapa_codigo[k] = v
                self.log(f"Códigos carregados: {len(mapa_codigo)} registro(s).")
            else:
                self.log("[AVISO] sindicatosistema.xlsx sem colunas 'cnpj' e/ou 'codigo'.")
        except Exception as e:
            self.log(f"[AVISO] Não foi possível ler sindicatosistema.xlsx: {e}")

        limpar_temp()

        self.rel_nao_encontrados = []
        self.rel_ja_baixados = []
        self.rel_baixados = []

        self.log("Iniciando Chrome...")
        driver = configurar_driver(headless=headless)

        for index, sindicato in enumerate(sindicatos):
            # Verifica abortamento a cada sindicato
            if self._verificar_abortar(execucao):
                self.log(f"\n[ABORTADO] Execução {execucao.id} marcada para abortar. Encerrando...")
                execucao.status = ExecucaoScraper.STATUS_ABORTADO
                execucao.save(update_fields=["status"])
                driver.quit()
                return

            cnpj_digits = limpar_cnpj(sindicato.cnpj or "")
            if not cnpj_digits or len(cnpj_digits) != 14:
                self.log(f"[LINHA {index}] CNPJ inválido para '{sindicato.nome}' — pulando.")
                continue

            cnpj_formatado = formatar_cnpj(cnpj_digits)
            sindicato_esperado = str(sindicato.codigo or sindicato.nome).strip()

            self.log(f"\n{'='*60}")
            self.log(f"[{index}] CNPJ: {cnpj_formatado}  |  Sindicato: {sindicato_esperado}  |  Nome: {sindicato.nome}")
            self.log('='*60)

            # Acessar site
            try:
                driver.get("https://www3.mte.gov.br/sistemas/mediador/ConsultarInstColetivo")
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "chkNRCNPJ"))
                )
            except Exception as e:
                self.log(f"  [ERRO] Página não carregou: {e}")
                continue

            # Marcar checkbox CNPJ e preencher
            try:
                chk = driver.find_element(By.ID, "chkNRCNPJ")
                if not chk.is_selected():
                    driver.execute_script("arguments[0].click();", chk)
                time.sleep(0.5)
                ipt = driver.find_element(By.ID, "txtNRCNPJ")
                ipt.clear()
                driver.execute_script("arguments[0].value = arguments[1];", ipt, cnpj_formatado)
                ipt.click()
                self.log(f"  CNPJ preenchido: {cnpj_formatado}")
            except Exception as e:
                self.log(f"  [ERRO] Preenchimento do CNPJ: {e}")
                continue

            # Selecionar Vigentes
            try:
                sel = Select(driver.find_element(By.ID, "cboSTVigencia"))
                try:
                    sel.select_by_value("1")
                except Exception:
                    sel.select_by_visible_text("Vigentes")
                self.log("  Vigência: Vigentes")
            except Exception as e:
                self.log(f"  [AVISO] Seleção de vigência: {e}")

            # Clicar em Pesquisar
            try:
                btn = driver.find_element(By.ID, "btnPesquisar")
                driver.execute_script("arguments[0].click();", btn)
                self.log("  Pesquisar clicado. Aguardando resultados...")
            except Exception as e:
                self.log(f"  [ERRO] Botão Pesquisar: {e}")
                continue

            # Lida com alerta JS
            try:
                WebDriverWait(driver, 3).until(EC.alert_is_present())
                alerta_txt = driver.switch_to.alert.text
                self.log(f"  [ALERTA] {alerta_txt} — pulando este CNPJ.")
                driver.switch_to.alert.accept()
                continue
            except Exception:
                pass

            # Aguardar resultados
            encontrou_resultado = False
            try:
                WebDriverWait(driver, 10).until(
                    EC.visibility_of_element_located((By.ID, "divExibirConsultaDetalhada"))
                )
                encontrou_resultado = True
            except Exception:
                pass

            if not encontrou_resultado:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                body_norm = normalizar_texto(body_text)
                sem_resultado_frases = [
                    "NENHUM REGISTRO", "NENHUM RESULTADO", "NAO FORAM ENCONTRADOS",
                    "NAO HA INSTRUMENTOS", "NAO ENCONTRADO",
                ]
                if any(f in body_norm for f in sem_resultado_frases):
                    self.log("  [SEM RESULTADO] Nenhum instrumento coletivo encontrado para este CNPJ.")
                else:
                    self.log("  [AVISO] Tabela não apareceu em 20s. Verifique manualmente.")
                self.rel_nao_encontrados.append((cnpj_formatado, sindicato_esperado))
                continue

            # Percorrer páginas
            achou_match = False
            num_pagina = 1

            while True:
                # Verifica abortamento a cada página
                if self._verificar_abortar(execucao):
                    self.log(f"\n[ABORTADO] Execução {execucao.id} marcada para abortar (paginação). Encerrando...")
                    execucao.status = ExecucaoScraper.STATUS_ABORTADO
                    execucao.save(update_fields=["status"])
                    driver.quit()
                    return
                self.log(f"\n  --- Página {num_pagina} de resultados ---")

                try:
                    linhas = driver.find_elements(By.CSS_SELECTOR, "#grdInstrumentos tr[indice]")
                    if not linhas:
                        linhas = driver.find_elements(By.CSS_SELECTOR, "#divConsultaDetalhada table tr")
                        linhas = [l for l in linhas if l.find_elements(By.TAG_NAME, "td")]
                except Exception as e:
                    self.log(f"  [ERRO] Leitura da tabela (pág {num_pagina}): {e}")
                    break

                if not linhas:
                    if num_pagina == 1:
                        self.log("  [SEM RESULTADO] Tabela carregou mas não há linhas de dados.")
                        self.rel_nao_encontrados.append((cnpj_formatado, sindicato_esperado))
                    break

                self.log(f"  Linhas encontradas: {len(linhas)}")

                for i, linha in enumerate(linhas):
                    # Verifica abortamento a cada linha
                    if self._verificar_abortar(execucao):
                        self.log(f"\n[ABORTADO] Execução {execucao.id} marcada para abortar (linha). Encerrando...")
                        execucao.status = ExecucaoScraper.STATUS_ABORTADO
                        execucao.save(update_fields=["status"])
                        driver.quit()
                        return
                    janela_original = driver.current_window_handle
                    try:
                        texto_linha = linha.text
                        texto_norm = normalizar_texto(texto_linha)

                        # Detecta tipo
                        tipo_raw = ""
                        m_tipo = re.search(
                            r'TIPO DO INSTRUMENTO\s*([\w\s]+?)(?:VIGENCIA|PARTES|$)',
                            texto_norm, re.IGNORECASE
                        )
                        if m_tipo:
                            tipo_raw = m_tipo.group(1).strip()
                        tipo_check = tipo_raw if tipo_raw else texto_norm

                        is_tipo_valido = (
                            "CONVENCAO COLETIVA" in tipo_check or
                            "TERMO ADITIVO" in tipo_check
                        )

                        # Detecta partes
                        partes_raw = ""
                        m_partes = re.search(r'PARTES\s*(.+?)$', texto_norm, re.IGNORECASE | re.DOTALL)
                        if m_partes:
                            partes_raw = m_partes.group(1).strip()

                        segunda_parte_ok = e_sindicato_ou_federacao(partes_raw if partes_raw else texto_norm)

                        motivo_rejeicao = ""
                        if not is_tipo_valido:
                            motivo_rejeicao = f"tipo invalido ('{tipo_raw}')"
                        elif not segunda_parte_ok:
                            motivo_rejeicao = "2a parte nao e sindicato/federacao (parece empresa)"

                        self.log(f"\n  [Pág {num_pagina} / Linha {i}] tipo_ok={is_tipo_valido} ('{tipo_raw}') | sind_fed_ok={segunda_parte_ok}")

                        if motivo_rejeicao:
                            self.log(f"    IGNORADO: {motivo_rejeicao}")
                            continue

                        achou_match = True
                        self.log(f"  [MATCH] Pág {num_pagina} / Linha {i}. Baixando...")

                        # Data de início de vigência
                        inicio_vigencia = "DATA_DESCONHECIDA"
                        m_data = re.search(r'(\d{2}/\d{2}/\d{4})', texto_linha)
                        if m_data:
                            inicio_vigencia = m_data.group(1).replace('/', '-')

                        tipo_arq = "TA-CCT" if "TERMO ADITIVO" in tipo_check else "CCT"
                        codigo_sind = mapa_codigo.get(cnpj_digits, sindicato.codigo or "")
                        prefixo = f"{codigo_sind}-" if codigo_sind else ""

                        nome_esperado = formatar_nome_arquivo(
                            f"{prefixo}{tipo_arq}", sindicato_esperado, inicio_vigencia
                        )

                        # Verifica se já existe no disco (ignora se --forcar)
                        ja_existe = False
                        if not forcar:
                            ja_existe = any(
                                os.path.exists(os.path.join(DOWNLOAD_DIR, f"{nome_esperado}{ext}"))
                                for ext in ['.pdf', '.doc', '.docx']
                            )

                        # Também verifica no banco por DocumentoCCT já existente para o mesmo sindicato/tipo/data (ignora se --forcar)
                        data_obj = parse_data_br(inicio_vigencia)
                        sindicato_db = None
                        try:
                            sindicato_db = Sindicato.objects.get(cnpj=cnpj_digits)
                        except Sindicato.DoesNotExist:
                            pass

                        if not forcar and (ja_existe or (sindicato_db and DocumentoCCT.objects.filter(
                            sindicato=sindicato_db, tipo=tipo_arq, data_inicio_vigencia=data_obj
                        ).exists())):
                            self.log(f"  [PULANDO] Arquivo já existe: {nome_esperado}")
                            self.rel_ja_baixados.append((cnpj_formatado, sindicato_esperado, nome_esperado))
                            continue

                        if forcar:
                            self.log(f"  [FORÇAR] Re-download ativado. Baixando mesmo se existir: {nome_esperado}")

                        limpar_temp()

                        # ==========================================
                        # DOWNLOAD DO ARQUIVO (direto primeiro, legado como fallback)
                        # ==========================================
                        destino_final = None
                        link = linha.find_element(By.TAG_NAME, "a")

                        # TENTATIVA 1: Download direto via requests (mais rápido e confiável)
                        destino_base = os.path.join(DOWNLOAD_DIR, nome_esperado)
                        destino_final = baixar_arquivo_direto(
                            driver, link, destino_base, log_func=self.log
                        )

                        # TENTATIVA 2: Fluxo legado com Selenium (nova janela)
                        if not destino_final:
                            limpar_temp()
                            driver.execute_script("arguments[0].click();", link)

                            try:
                                WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > 1)
                                for h in driver.window_handles:
                                    if h != janela_original:
                                        driver.switch_to.window(h)
                                        break
                                self.log("  Nova janela aberta. Aguardando download...")
                                time.sleep(2)
                                try:
                                    btn_dl = WebDriverWait(driver, 5).until(
                                        EC.element_to_be_clickable((By.XPATH,
                                            "//*[contains(translate(text(),'DOWNLOAD','download'),'download')] | "
                                            "//input[contains(translate(@value,'DOWNLOAD','download'),'download')]"
                                        ))
                                    )
                                    btn_dl.click()
                                except Exception:
                                    pass
                            except Exception:
                                self.log("  Sem nova janela — download pode ser direto.")

                            arq_baixado = aguardar_download(TEMP_DL_DIR, timeout=20, abortar_check=lambda: self._verificar_abortar(execucao))
                            if arq_baixado == "__ABORTADO__":
                                self.log("  [ABORTADO] Download interrompido por solicitação de abort.")
                                execucao.status = ExecucaoScraper.STATUS_ABORTADO
                                execucao.save(update_fields=["status"])
                                driver.quit()
                                return
                            if arq_baixado:
                                ext_arq = os.path.splitext(arq_baixado)[1].lower()
                                destino = os.path.join(DOWNLOAD_DIR, f"{nome_esperado}{ext_arq}")
                                if os.path.exists(destino):
                                    os.remove(destino)
                                shutil.move(arq_baixado, destino)
                                self.log(f"  [OK] Salvo (legado): {nome_esperado}{ext_arq}")
                                destino_final = destino
                            else:
                                self.log("  [AVISO] Arquivo não capturado em 20s.")

                            # Fecha janelas extras
                            for h in driver.window_handles:
                                if h != janela_original:
                                    try:
                                        driver.switch_to.window(h)
                                        driver.close()
                                    except Exception:
                                        pass
                            try:
                                driver.switch_to.window(janela_original)
                            except Exception:
                                pass

                        # ==========================================
                        # PÓS-DOWNLOAD: converte e registra no banco
                        # ==========================================
                        if destino_final:
                            ext_arq = os.path.splitext(destino_final)[1].lower()
                            if ext_arq in ('.doc', '.docx'):
                                destino_final = converter_para_pdf(destino_final)

                            nome_final = os.path.basename(destino_final)
                            self.rel_baixados.append((cnpj_formatado, sindicato_esperado, nome_final))
                            self.log(f"  [OK] Arquivo final: {nome_final}")

                            # Converte caminho absoluto para relativo ao BASE_DIR (funciona em Docker e local)
                            caminho_relativo = destino_final
                            try:
                                caminho_relativo = os.path.relpath(destino_final, BASE_DIR)
                            except ValueError:
                                pass  # mantém absoluto se não conseguir relativizar

                            # Registra no banco
                            if not sindicato_db:
                                codigo_busca = mapa_codigo.get(cnpj_digits, cnpj_digits)
                                sindicato_db, _ = Sindicato.objects.get_or_create(
                                    cnpj=cnpj_digits,
                                    defaults={
                                        "codigo": codigo_busca,
                                        "nome": sindicato_esperado,
                                    }
                                )

                            doc, created = DocumentoCCT.objects.get_or_create(
                                sindicato=sindicato_db,
                                tipo=tipo_arq,
                                data_inicio_vigencia=data_obj,
                                defaults={
                                    "arquivo_pdf": caminho_relativo,
                                    "status_extracao": DocumentoCCT.STATUS_EXTRAIDO,
                                }
                            )
                            if not created:
                                doc.arquivo_pdf = caminho_relativo
                                doc.status_extracao = DocumentoCCT.STATUS_EXTRAIDO
                                doc.save()

                            # Contabiliza corretamente: novo baixado vs já existente
                            if created:
                                execucao.total_baixados += 1
                            else:
                                execucao.total_ja_existentes += 1
                            execucao.save(update_fields=["total_baixados", "total_ja_existentes"])
                        else:
                            self.log("  [AVISO] Download não concluído.")
                            self.rel_nao_encontrados.append({"cnpj": cnpj_formatado, "sindicato": sindicato_esperado, "nome": sindicato.nome})

                    except Exception as e:
                        self.log(f"  [ERRO] Pág {num_pagina} / Linha {i}: {e}")
                        self.rel_nao_encontrados.append({"cnpj": cnpj_formatado, "sindicato": sindicato_esperado, "nome": sindicato.nome})
                    finally:
                        # Garante que sempre volta para a janela principal
                        try:
                            driver.switch_to.window(janela_original)
                        except Exception:
                            pass

                # Próxima página
                try:
                    btn_proxima = None
                    candidatos = driver.find_elements(By.XPATH,
                        "//*[@id='divConsultaDetalhada']//a[contains(normalize-space(text()),'>')] | "
                        "//*[@id='divConsultaDetalhada']//a[contains(translate(normalize-space(text()),"
                        "'PRÓXIMAPRÓXIMA','proximaproximA'),'proxima')] | "
                        "//*[@id='divConsultaDetalhada']//input[contains(translate(@value,"
                        "'PRÓXIMA','proxima'),'proxima')]"
                    )
                    for cand in candidatos:
                        if cand.is_displayed() and cand.is_enabled():
                            cls = cand.get_attribute("class") or ""
                            aria = cand.get_attribute("aria-disabled") or ""
                            if "disabled" not in cls.lower() and aria.lower() != "true":
                                btn_proxima = cand
                                break

                    if not btn_proxima:
                        prox_num = str(num_pagina + 1)
                        num_links = driver.find_elements(By.XPATH,
                            f"//*[@id='divConsultaDetalhada']//a[normalize-space(text())='{prox_num}']"
                        )
                        for nl in num_links:
                            if nl.is_displayed() and nl.is_enabled():
                                btn_proxima = nl
                                break

                    if btn_proxima:
                        num_pagina += 1
                        self.log(f"\n  [PAGINAÇÃO] Avançando para a página {num_pagina}...")
                        driver.execute_script("arguments[0].click();", btn_proxima)
                        # Verifica abortar antes de dormir
                        if self._verificar_abortar(execucao):
                            self.log(f"\n[ABORTADO] Execução {execucao.id} marcada para abortar (paginação sleep). Encerrando...")
                            execucao.status = ExecucaoScraper.STATUS_ABORTADO
                            execucao.save(update_fields=["status"])
                            driver.quit()
                            return
                        time.sleep(2)
                        try:
                            WebDriverWait(driver, 10).until(
                                EC.visibility_of_element_located((By.ID, "divExibirConsultaDetalhada"))
                            )
                        except Exception:
                            pass
                    else:
                        self.log(f"  [PAGINAÇÃO] Sem próxima página. Total de páginas lidas: {num_pagina}.")
                        break
                except Exception as e:
                    self.log(f"  [PAGINAÇÃO] Erro ao verificar próxima página: {e}")
                    break

            if not achou_match:
                self.log("  [SEM MATCH] Nenhuma linha passou em todos os critérios para este CNPJ.")
                self.rel_nao_encontrados.append((cnpj_formatado, sindicato_esperado))

            # Persiste progresso a cada sindicato
            self._salvar_progresso(execucao)

        driver.quit()
        self.log("\n" + "="*60)
        self.log("Processamento finalizado!")
        self.log(f"Arquivos salvos em: {DOWNLOAD_DIR}")
        self.log("="*60)

        # Resumo
        execucao.total_baixados = len(self.rel_baixados)
        execucao.total_ja_existentes = len(self.rel_ja_baixados)
        execucao.total_nao_encontrados = len(self.rel_nao_encontrados)
        execucao.nao_encontrados_json = self.rel_nao_encontrados
        execucao.save()

        self.log(f"\nRESUMO: {len(self.rel_baixados)} baixado(s) | {len(self.rel_ja_baixados)} já existia(m) | {len(self.rel_nao_encontrados)} não encontrado(s)")
