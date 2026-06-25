"""
redownload_docs.py
==================
Re-baixa os arquivos .doc originais do Mediador MTE para todos os PDFs
que existem em 'convencoes/' mas nao possuem o .doc correspondente em
'convencoes/convencoesdoc/'.

Logica:
  1. Lista PDFs sem .doc correspondente
  2. Extrai o codigo do inicio do nome (ex: '356-CCT-...' -> codigo=356)
  3. Mapeia codigo -> CNPJ via sindicatosistema.xlsx
  4. Extrai a data de inicio de vigencia do nome do arquivo
  5. Busca no Mediador pelo CNPJ, localiza o documento pela data e tipo
  6. Baixa o .doc e salva em convencoesdoc/ com o mesmo nome base do PDF
"""

import os, re, time, shutil, unicodedata
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ── Diretorios ─────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONV_DIR   = os.path.join(BASE_DIR, "convencoes")
DOC_DIR    = os.path.join(CONV_DIR, "convencoesdoc")
SIS_FILE   = os.path.join(BASE_DIR, "sindicatosistema.xlsx")
TEMP_DIR   = os.path.join(BASE_DIR, "temp_dl")

os.makedirs(DOC_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# ── Helpers ────────────────────────────────────────────────────────────────────
def normalizar(texto):
    txt = str(texto)
    txt = unicodedata.normalize('NFD', txt).encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'\s+', ' ', txt).upper().strip()

def limpar_cnpj(cnpj):
    s = str(cnpj)
    if s.endswith('.0'): s = s[:-2]
    return re.sub(r'[^0-9]', '', s).zfill(14)

def formatar_cnpj(digits):
    c = digits.zfill(14)
    return f"{c[0:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"

def aguardar_download(diretorio, timeout=45):
    inicio = time.time()
    while time.time() - inicio < timeout:
        arqs = [f for f in os.listdir(diretorio)
                if not f.endswith('.crdownload') and not f.endswith('.tmp')]
        if arqs:
            time.sleep(2)
            return os.path.join(diretorio, arqs[0])
        time.sleep(1)
    return None

def limpar_temp():
    for f in os.listdir(TEMP_DIR):
        try: os.remove(os.path.join(TEMP_DIR, f))
        except: pass

# ── Carrega mapa codigo -> cnpj ────────────────────────────────────────────────
def carregar_mapa():
    df = pd.read_excel(SIS_FILE)
    col_cnpj   = next((c for c in df.columns if 'cnpj'   in str(c).lower()), None)
    col_codigo = next((c for c in df.columns if 'codigo' in str(c).lower()), None)
    if not col_cnpj or not col_codigo:
        raise ValueError("Colunas 'cnpj' e/ou 'codigo' nao encontradas em sindicatosistema.xlsx")
    mapa = {}
    for _, row in df.iterrows():
        cod  = str(row[col_codigo]).strip()
        cnpj = limpar_cnpj(row[col_cnpj])
        mapa[cod] = cnpj
    return mapa

# ── Identifica PDFs sem .doc ───────────────────────────────────────────────────
def pdfs_sem_doc():
    docs_existentes = {
        os.path.splitext(f)[0].upper()
        for f in os.listdir(DOC_DIR)
        if f.lower().endswith(('.doc', '.docx'))
    }
    pendentes = []
    for f in sorted(os.listdir(CONV_DIR)):
        if not f.lower().endswith('.pdf'): continue
        if not os.path.isfile(os.path.join(CONV_DIR, f)): continue
        nome_sem_ext = os.path.splitext(f)[0]
        if nome_sem_ext.upper() not in docs_existentes:
            pendentes.append(f)
    return pendentes

# ── Extrai info do nome do arquivo ─────────────────────────────────────────────
def extrair_info(nome_pdf):
    """
    Retorna (codigo, tipo, data_str) a partir do nome.
    Ex: '356-CCT-SIND DOS MOTORISTAS...-01-01-2026.pdf'
        -> ('356', 'CCT', '01/01/2026')
    """
    nome = os.path.splitext(nome_pdf)[0]
    partes = nome.split('-')

    codigo = ''
    tipo   = ''
    data   = ''

    # Codigo: primeiro segmento se for numerico
    if partes and partes[0].strip().isdigit():
        codigo = partes[0].strip()
        partes = partes[1:]

    # Tipo: proximo segmento (CCT ou TA)
    if partes:
        if partes[0].strip().upper() in ('CCT', 'TA'):
            tipo_raw = partes[0].strip().upper()
            partes   = partes[1:]
            if tipo_raw == 'TA' and partes and partes[0].strip().upper() == 'CCT':
                tipo_raw = 'TA-CCT'
                partes   = partes[1:]
            tipo = tipo_raw

    # Data: ultimo segmento no formato DD-MM-YYYY
    m = re.search(r'(\d{2})-(\d{2})-(\d{4})$', nome)
    if m:
        data = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"

    return codigo, tipo, data

# ── Configura Chrome ───────────────────────────────────────────────────────────
def configurar_driver():
    options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": os.path.abspath(TEMP_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": False,  # queremos o .doc, nao PDF
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

# ── Faz download do .doc para um PDF especifico ────────────────────────────────
def buscar_no_mediador(driver, cnpj_fmt, vigencia_value, data_vigencia, tipo, nome_base):
    """
    Acessa o Mediador com um filtro de vigência específico, localiza o documento
    pela data e tipo, baixa o .doc e salva em DOC_DIR.
    Retorna True se baixou com sucesso.
    """
    janela_original = driver.current_window_handle

    driver.get("https://www3.mte.gov.br/sistemas/mediador/ConsultarInstColetivo")
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "chkNRCNPJ")))
    except:
        print("    [ERRO] Pagina nao carregou.")
        return False

    try:
        chk = driver.find_element(By.ID, "chkNRCNPJ")
        if not chk.is_selected():
            driver.execute_script("arguments[0].click();", chk)
        time.sleep(0.4)
        ipt = driver.find_element(By.ID, "txtNRCNPJ")
        driver.execute_script("arguments[0].value = arguments[1];", ipt, cnpj_fmt)
        ipt.click()
    except Exception as e:
        print(f"    [ERRO] Preenchimento CNPJ: {e}")
        return False

    try:
        sel = Select(driver.find_element(By.ID, "cboSTVigencia"))
        try:    sel.select_by_value(vigencia_value)
        except: sel.select_by_index(0)
        driver.execute_script("arguments[0].click();", driver.find_element(By.ID, "btnPesquisar"))
    except Exception as e:
        print(f"    [ERRO] Pesquisa: {e}")
        return False

    try:
        WebDriverWait(driver, 3).until(EC.alert_is_present())
        driver.switch_to.alert.accept()
        return False
    except: pass

    try:
        WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.ID, "divExibirConsultaDetalhada"))
        )
    except:
        return False

    num_pagina = 1
    while True:
        linhas = driver.find_elements(By.CSS_SELECTOR, "#grdInstrumentos tr[indice]")
        if not linhas:
            linhas = [l for l in driver.find_elements(By.CSS_SELECTOR, "#divConsultaDetalhada table tr")
                      if l.find_elements(By.TAG_NAME, "td")]

        for linha in linhas:
            texto = normalizar(linha.text)

            tipo_ok = False
            if tipo == 'CCT' and 'CONVENCAO COLETIVA' in texto:
                tipo_ok = True
            elif tipo in ('TA', 'TA-CCT') and 'TERMO ADITIVO' in texto:
                tipo_ok = True

            data_norm = data_vigencia.replace('/', '-')
            data_ok   = data_norm in texto or data_vigencia in texto

            if tipo_ok and data_ok:
                print(f"    [MATCH] Linha encontrada. Baixando .doc...")
                limpar_temp()
                try:
                    link = linha.find_element(By.TAG_NAME, "a")
                    driver.execute_script("arguments[0].click();", link)
                except Exception as e:
                    print(f"    [ERRO] Clique no link: {e}")
                    return False

                try:
                    WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > 1)
                    for h in driver.window_handles:
                        if h != janela_original:
                            driver.switch_to.window(h)
                            break
                    time.sleep(2)
                    try:
                        btn = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH,
                                "//*[contains(translate(text(),'DOWNLOAD','download'),'download')] | "
                                "//input[contains(translate(@value,'DOWNLOAD','download'),'download')]"
                            ))
                        )
                        btn.click()
                    except: pass
                except:
                    print("    Sem nova janela — download direto.")

                arq = aguardar_download(TEMP_DIR, timeout=45)
                for h in driver.window_handles:
                    if h != janela_original:
                        try:
                            driver.switch_to.window(h)
                            driver.close()
                        except: pass
                driver.switch_to.window(janela_original)

                if arq:
                    ext_arq = os.path.splitext(arq)[1]
                    destino = os.path.join(DOC_DIR, f"{nome_base}{ext_arq}")
                    if os.path.exists(destino): os.remove(destino)
                    shutil.move(arq, destino)
                    print(f"    [OK] Salvo em convencoesdoc: {os.path.basename(destino)}")
                    return True
                else:
                    print("    [AVISO] Arquivo nao capturado em 45s.")
                    return False

        # Proxima pagina
        btn_prox = None
        for cand in driver.find_elements(By.XPATH,
                "//*[@id='divConsultaDetalhada']//a[contains(normalize-space(text()),'>')]"):
            cls  = cand.get_attribute("class") or ""
            aria = cand.get_attribute("aria-disabled") or ""
            if cand.is_displayed() and "disabled" not in cls.lower() and aria.lower() != "true":
                btn_prox = cand
                break
        if not btn_prox:
            prox = str(num_pagina + 1)
            for nl in driver.find_elements(By.XPATH,
                    f"//*[@id='divConsultaDetalhada']//a[normalize-space(text())='{prox}']"):
                if nl.is_displayed():
                    btn_prox = nl
                    break

        if btn_prox:
            num_pagina += 1
            driver.execute_script("arguments[0].click();", btn_prox)
            time.sleep(3)
        else:
            break

    return False


def baixar_doc(driver, cnpj_digits, data_vigencia, tipo, nome_base):
    """
    Tenta baixar o .doc primeiro filtrando por 'Vigentes'.
    Se nao encontrar, tenta sem filtro (todos os instrumentos).
    """
    cnpj_fmt = formatar_cnpj(cnpj_digits)

    # Tentativa 1: apenas vigentes
    resultado = buscar_no_mediador(driver, cnpj_fmt, "1", data_vigencia, tipo, nome_base)
    if resultado:
        return True

    # Tentativa 2: sem filtro de vigencia (documentos encerrados/expirados)
    print(f"    [RETRY] Nao encontrado em 'Vigentes'. Tentando sem filtro de vigencia...")
    resultado = buscar_no_mediador(driver, cnpj_fmt, "0", data_vigencia, tipo, nome_base)
    if resultado:
        return True

    print(f"    [NAO ENCONTRADO] Documento com data {data_vigencia} / tipo {tipo} nao localizado.")
    return False


# ── Main ───────────────────────────────────────────────────────────────────────
def reiniciar_driver(driver):
    """Fecha o driver atual com segurança e retorna um novo."""
    try:
        driver.quit()
    except Exception:
        pass
    time.sleep(3)
    return configurar_driver()

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("RE-DOWNLOAD DE .DOC — ARQUIVOS SEM ORIGINAL EM convencoesdoc")
    print("=" * 65)

    mapa_codigo = carregar_mapa()
    print(f"Mapa de codigos carregado: {len(mapa_codigo)} sindicato(s)\n")

    pendentes = pdfs_sem_doc()
    print(f"PDFs sem .doc correspondente: {len(pendentes)}\n")

    if not pendentes:
        print("Nenhum arquivo pendente. Tudo certo!")
        return

    driver = configurar_driver()
    limpar_temp()

    ok = 0
    falha = []

    for idx, nome_pdf in enumerate(pendentes, 1):
        print(f"\n[{idx}/{len(pendentes)}] {nome_pdf}")

        codigo, tipo, data = extrair_info(nome_pdf)
        print(f"  Codigo: {codigo} | Tipo: {tipo} | Data: {data}")

        if not codigo or not data:
            print("  [SKIP] Nao foi possivel extrair codigo ou data do nome do arquivo.")
            falha.append(nome_pdf)
            continue

        cnpj_digits = mapa_codigo.get(codigo)
        if not cnpj_digits:
            print(f"  [SKIP] Codigo '{codigo}' nao encontrado em sindicatosistema.xlsx")
            falha.append(nome_pdf)
            continue

        print(f"  CNPJ: {formatar_cnpj(cnpj_digits)}")
        nome_base = os.path.splitext(nome_pdf)[0]

        # Tenta com retry em caso de timeout ou falha de driver
        MAX_TENTATIVAS = 3
        sucesso = False
        for tentativa in range(1, MAX_TENTATIVAS + 1):
            try:
                sucesso = baixar_doc(driver, cnpj_digits, data, tipo, nome_base)
                break  # saiu sem excecao, para o loop de retry
            except Exception as e:
                err_str = str(e)
                if 'timeout' in err_str.lower() or 'timed out' in err_str.lower() or \
                   'connection' in err_str.lower() or 'read timeout' in err_str.lower():
                    print(f"  [TIMEOUT] Tentativa {tentativa}/{MAX_TENTATIVAS} falhou: {err_str[:120]}")
                    if tentativa < MAX_TENTATIVAS:
                        print("  Reiniciando Chrome e aguardando 10s...")
                        driver = reiniciar_driver(driver)
                        limpar_temp()
                        time.sleep(10)
                    else:
                        print("  Esgotadas as tentativas. Pulando este arquivo.")
                        sucesso = False
                else:
                    print(f"  [ERRO INESPERADO] {err_str[:200]}")
                    # Tenta reiniciar o driver mesmo assim
                    try:
                        driver = reiniciar_driver(driver)
                        limpar_temp()
                    except Exception:
                        pass
                    sucesso = False
                    break

        if sucesso:
            ok += 1
        else:
            falha.append(nome_pdf)

        time.sleep(2)  # pausa entre requisicoes para nao sobrecarregar o site

    driver.quit()

    print("\n" + "=" * 65)
    print(f"RESUMO: {ok} baixado(s) | {len(falha)} nao encontrado(s)")
    print("=" * 65)
    if falha:
        print("\nArquivos nao baixados (verificar manualmente):")
        for f in falha:
            print(f"  {f}")

if __name__ == "__main__":
    main()
