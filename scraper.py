import os
import time
import re
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import shutil
import unicodedata

# ==========================================
# CONFIGURAÇÕES DE DIRETÓRIOS E ARQUIVOS
# ==========================================
BASE_DIR             = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR         = os.path.join(BASE_DIR, "convencoes")
DOC_DIR              = os.path.join(DOWNLOAD_DIR, "convencoesdoc")  # .doc originais
EXCEL_FILE           = os.path.join(BASE_DIR, "cnpjs.xlsx")
SINDICATO_SIS_FILE   = os.path.join(BASE_DIR, "sindicatosistema.xlsx")
TEMP_DL_DIR          = os.path.join(BASE_DIR, "temp_dl")

for d in [DOWNLOAD_DIR, DOC_DIR, TEMP_DL_DIR]:
    os.makedirs(d, exist_ok=True)

# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================
def limpar_cnpj(cnpj):
    """Remove tudo que não for dígito e garante 14 caracteres."""
    s = str(cnpj)
    if s.endswith('.0'):
        s = s[:-2]
    return re.sub(r'[^0-9]', '', s).zfill(14)

def formatar_cnpj(cnpj_digits):
    """Formata 14 dígitos para XX.XXX.XXX/XXXX-XX (aceito pela página)."""
    c = cnpj_digits.zfill(14)
    return f"{c[0:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"

def formatar_nome_arquivo(tipo, sindicato, inicio_vigencia):
    """Monta o nome do arquivo e remove caracteres inválidos no Windows."""
    nome = f"{tipo}-{sindicato}-{inicio_vigencia}"
    nome = re.sub(r'[\\/*?:"<>|]', "", nome)
    return nome[:200]  # limita tamanho para evitar erros de path

def normalizar_texto(texto):
    """Remove acentos, caixa e espaços extras."""
    try:
        texto = str(texto)
        texto = unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode("utf-8")
        return re.sub(r'\s+', ' ', texto).upper().strip()
    except:
        return str(texto).upper().strip()

# Padrões que identificam SINDICATO ou FEDERAÇÃO (incluindo abreviados)
_PADRAO_SIND_FED = re.compile(
    r'\b('
    r'SINDICATO|SIND\b|SINDI\b|SINTR|SINTEC|SINTRAF|SINTESP|SINDICAD|'
    r'FEDERAC|FEDERA|FED\b|FEDER\b|CONFEDERAC|CONFEDER|CONF\b|'
    r'CENTRAL|UNIAO|ASSOCIAC|ASSOCIA'
    r')', re.IGNORECASE
)

# Sufixos EXCLUSIVAMENTE de empresa — jamais aparecem em nome de sindicato
# ATENÇÃO: NÃO incluir palavras como INDUSTRIA, COMERCIO, SERVICOS, pois
# essas palavras aparecem frequentemente em nomes de sindicatos
# (ex: "Sindicato dos Trabalhadores na Indústria do Comércio")
_PADRAO_EMPRESA = re.compile(
    r'\b('
    r'LTDA|S\.A\b|S/A\b|EIRELI|EPP\b|MEI\b|'
    r'(?<!\w)ME(?!\w)'   # "ME" apenas como palavra isolada
    r')', re.IGNORECASE
)

def e_sindicato_ou_federacao(texto_parte):
    """
    Retorna True se o texto indica sindicato ou federação.
    Retorna False se parece ser exclusivamente uma empresa.

    Regra:
      - Se contém indicador de sindicato/federação → True (sempre, independente de outras palavras)
      - Se NÃO contém sindicato/federação E contém sufixo legal de empresa → False
      - Se nenhum dos dois → False (entidade desconhecida, não baixa)
    """
    t = normalizar_texto(texto_parte)
    tem_sind_fed = bool(_PADRAO_SIND_FED.search(t))
    tem_empresa  = bool(_PADRAO_EMPRESA.search(t))

    if tem_sind_fed:
        return True          # tem sindicato/federação → aceita sempre
    if tem_empresa:
        return False         # só empresa, sem sindicato → rejeita
    return False             # entidade não identificada → rejeita por segurança

def aguardar_download(diretorio, timeout=40):
    """Aguarda um arquivo válido aparecer no diretório."""
    inicio = time.time()
    while time.time() - inicio < timeout:
        arquivos = [f for f in os.listdir(diretorio)
                    if not f.endswith('.crdownload') and not f.endswith('.tmp')]
        if arquivos:
            time.sleep(2)  # garante que o arquivo terminou de ser escrito
            return os.path.join(diretorio, arquivos[0])
        time.sleep(1)
    return None

def limpar_temp():
    """Remove todos os arquivos da pasta temporária."""
    for f in os.listdir(TEMP_DL_DIR):
        try:
            os.remove(os.path.join(TEMP_DL_DIR, f))
        except:
            pass

def converter_para_pdf(caminho_doc):
    """
    Converte um arquivo .doc/.docx para .pdf usando o Microsoft Word.
    - O PDF fica na pasta 'convencoes' (mesma pasta do .doc original).
    - O .doc original e movido para a subpasta 'convencoesdoc' (nao e excluido).
    Retorna o caminho do PDF gerado (ou o .doc se a conversao falhar).
    """
    ext = os.path.splitext(caminho_doc)[1].lower()
    if ext not in ('.doc', '.docx'):
        return caminho_doc  # ja e PDF ou outro formato

    abs_doc = os.path.abspath(caminho_doc)
    nome_base = os.path.splitext(os.path.basename(caminho_doc))[0]

    # PDF fica na mesma pasta do .doc (convencoes/)
    abs_pdf = os.path.join(os.path.dirname(abs_doc), nome_base + '.pdf')

    # .doc vai para convencoesdoc/
    destino_doc = os.path.join(DOC_DIR, os.path.basename(caminho_doc))

    print(f"  Convertendo para PDF: {os.path.basename(caminho_doc)} ...")
    try:
        import win32com.client
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        try:
            doc = word.Documents.Open(abs_doc)
            doc.SaveAs(abs_pdf, FileFormat=17)  # 17 = wdFormatPDF
            doc.Close(False)
            print(f"  [OK] PDF gerado: {os.path.basename(abs_pdf)}")

            # Move o .doc original para convencoesdoc (sem excluir)
            try:
                if os.path.exists(destino_doc):
                    os.remove(destino_doc)
                shutil.move(abs_doc, destino_doc)
                print(f"  [OK] .doc movido para convencoesdoc: {os.path.basename(destino_doc)}")
            except Exception as e_mv:
                print(f"  [AVISO] Nao foi possivel mover o .doc original: {e_mv}")

            return abs_pdf
        except Exception as e:
            print(f"  [ERRO] Falha ao converter {os.path.basename(caminho_doc)}: {e}")
            return caminho_doc  # retorna o .doc mesmo assim
        finally:
            try:
                word.Quit()
            except:
                pass
    except ImportError:
        print("  [AVISO] pywin32 nao instalado - arquivo mantido como .doc")
        print("          Instale com: python -m pip install pywin32")
        return caminho_doc
    except Exception as e:
        print(f"  [ERRO] Nao foi possivel iniciar o Microsoft Word: {e}")
        return caminho_doc

# ==========================================
# CONFIGURAÇÃO DO SELENIUM E CHROME
# ==========================================
def configurar_driver():
    options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": os.path.abspath(TEMP_DL_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver

# ==========================================
# FLUXO PRINCIPAL
# ==========================================
def processar_mediador():
    # 1. Ler planilha
    try:
        df = pd.read_excel(EXCEL_FILE)
    except Exception as e:
        print(f"[ERRO] Não foi possível ler {EXCEL_FILE}: {e}")
        return

    col_cnpj      = next((c for c in df.columns if 'cnpj'      in str(c).lower()), None)
    col_sindicato  = next((c for c in df.columns if 'sindicato' in str(c).lower()), None)

    if not col_cnpj or not col_sindicato:
        print("[ERRO] Colunas 'cnpj' ou 'sindicato' não encontradas.")
        print("Colunas disponíveis:", df.columns.tolist())
        return

    print(f"Planilha lida com sucesso: {len(df)} linha(s).")
    print(f"  Coluna CNPJ      : {col_cnpj}")
    print(f"  Coluna Sindicato : {col_sindicato}\n")

    # 1b. Carregar tabela de códigos do sistema (sindicatosistema.xlsx)
    # Monta dicionário: cnpj_digits -> codigo  (ex: '19933049000125' -> '356')
    mapa_codigo = {}
    try:
        df_sis = pd.read_excel(SINDICATO_SIS_FILE)
        col_sis_cnpj   = next((c for c in df_sis.columns if 'cnpj'   in str(c).lower()), None)
        col_sis_codigo = next((c for c in df_sis.columns if 'codigo' in str(c).lower()), None)
        if col_sis_cnpj and col_sis_codigo:
            for _, r in df_sis.iterrows():
                k = limpar_cnpj(r[col_sis_cnpj])   # chave = 14 dígitos
                v = str(r[col_sis_codigo]).strip()
                mapa_codigo[k] = v
            print(f"Códigos de sindicatos carregados: {len(mapa_codigo)} registro(s) em sindicatosistema.xlsx")
        else:
            print("[AVISO] sindicatosistema.xlsx não possui colunas 'cnpj' e/ou 'codigo'. Prosseguindo sem prefixo.")
    except Exception as e:
        print(f"[AVISO] Não foi possível ler sindicatosistema.xlsx: {e}. Prosseguindo sem prefixo.")

    limpar_temp()

    # ==========================================
    # ESTRUTURAS DE RELATÓRIO
    # ==========================================
    rel_nao_encontrados  = []  # CNPJ sem nenhum registro no site
    rel_ja_baixados      = []  # CNPJ encontrado mas arquivo já existia
    rel_baixados         = []  # CNPJ encontrado e arquivo baixado com sucesso

    # 2. Iniciar navegador
    print("Iniciando Chrome...")
    driver = configurar_driver()

    for index, row in df.iterrows():
        cnpj_raw = row[col_cnpj]
        if pd.isna(cnpj_raw):
            print(f"[LINHA {index}] CNPJ vazio — pulando.")
            continue

        cnpj_digits   = limpar_cnpj(cnpj_raw)
        cnpj_formatado = formatar_cnpj(cnpj_digits)
        sindicato_esperado = str(row[col_sindicato]).strip()

        print(f"\n{'='*60}")
        print(f"[LINHA {index}] CNPJ: {cnpj_formatado}  |  Sindicato: {sindicato_esperado}")
        print('='*60)

        # 2. Acessar site
        try:
            driver.get("https://www3.mte.gov.br/sistemas/mediador/ConsultarInstColetivo")
            # Aguarda o formulário carregar
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "chkNRCNPJ"))
            )
        except Exception as e:
            print(f"  [ERRO] Página não carregou: {e}")
            continue

        # 3. Marcar checkbox CNPJ e preencher campo
        try:
            chk = driver.find_element(By.ID, "chkNRCNPJ")
            if not chk.is_selected():
                driver.execute_script("arguments[0].click();", chk)
            time.sleep(0.5)

            # O campo aceita CNPJ formatado (o JS faz a validação no blur)
            ipt = driver.find_element(By.ID, "txtNRCNPJ")
            ipt.clear()
            # Digita o CNPJ formatado diretamente via JavaScript para contornar a máscara
            driver.execute_script("arguments[0].value = arguments[1];", ipt, cnpj_formatado)
            ipt.click()  # dispara qualquer evento que precise do foco
            print(f"  CNPJ preenchido: {cnpj_formatado}")
        except Exception as e:
            print(f"  [ERRO] Preenchimento do CNPJ: {e}")
            continue

        # 4. Selecionar Vigentes
        try:
            sel = Select(driver.find_element(By.ID, "cboSTVigencia"))
            # Tenta pelo value='1' (Vigentes); se falhar, tenta pelo texto
            try:
                sel.select_by_value("1")
            except:
                sel.select_by_visible_text("Vigentes")
            print("  Vigência: Vigentes")
        except Exception as e:
            print(f"  [AVISO] Seleção de vigência: {e}")

        # 5. Clicar em Pesquisar
        try:
            btn = driver.find_element(By.ID, "btnPesquisar")
            driver.execute_script("arguments[0].click();", btn)
            print("  Pesquisar clicado. Aguardando resultados...")
        except Exception as e:
            print(f"  [ERRO] Botão Pesquisar: {e}")
            continue

        # Lida com alerta JS (ex: "CNPJ inválido")
        try:
            WebDriverWait(driver, 3).until(EC.alert_is_present())
            alerta_txt = driver.switch_to.alert.text
            print(f"  [ALERTA] {alerta_txt} — pulando este CNPJ.")
            driver.switch_to.alert.accept()
            continue
        except:
            pass

        # 6. Aguardar tabela de resultados OU mensagem de "nenhum registro"
        encontrou_resultado = False
        try:
            WebDriverWait(driver, 20).until(
                EC.visibility_of_element_located((By.ID, "divExibirConsultaDetalhada"))
            )
            encontrou_resultado = True
        except:
            pass

        if not encontrou_resultado:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            body_norm = normalizar_texto(body_text)

            sem_resultado_frases = [
                "NENHUM REGISTRO",
                "NENHUM RESULTADO",
                "NAO FORAM ENCONTRADOS",
                "NAO HA INSTRUMENTOS",
                "NAO ENCONTRADO",
            ]
            if any(f in body_norm for f in sem_resultado_frases):
                print("  [SEM RESULTADO] Nenhum instrumento coletivo encontrado para este CNPJ.")
            else:
                print("  [AVISO] Tabela não apareceu em 20s. Verifique manualmente.")
                print(f"  Texto visível da página (primeiros 300 chars): {body_text[:300]}")
            rel_nao_encontrados.append((cnpj_formatado, sindicato_esperado))
            continue

        # 7. Percorrer TODAS as páginas de resultados
        # NOVA REGRA:
        # - O CNPJ já é o filtro da pesquisa (qualquer resultado é daquele CNPJ)
        # - Baixar apenas se: tipo = CCT ou Termo Aditivo
        #                  E a 2ª parte for sindicato ou federação (não empresa)
        achou_match = False
        num_pagina  = 1

        while True:
            print(f"\n  --- Página {num_pagina} de resultados ---")

            # Lê linhas da página atual
            try:
                linhas = driver.find_elements(By.CSS_SELECTOR, "#grdInstrumentos tr[indice]")
                if not linhas:
                    linhas = driver.find_elements(By.CSS_SELECTOR, "#divConsultaDetalhada table tr")
                    linhas = [l for l in linhas if l.find_elements(By.TAG_NAME, "td")]
            except Exception as e:
                print(f"  [ERRO] Leitura da tabela (pág {num_pagina}): {e}")
                break

            if not linhas:
                if num_pagina == 1:
                    print("  [SEM RESULTADO] Tabela carregou mas não há linhas de dados.")
                    rel_nao_encontrados.append((cnpj_formatado, sindicato_esperado))
                break

            print(f"  Linhas encontradas: {len(linhas)}")

            # 8. Validar e baixar cada linha da página atual
            for i, linha in enumerate(linhas):
                janela_original = driver.current_window_handle
                try:
                    texto_linha = linha.text
                    texto_norm  = normalizar_texto(texto_linha)

                    # ---- Detecta TIPO DO INSTRUMENTO ----
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
                        "TERMO ADITIVO"       in tipo_check
                    )

                    # ---- Detecta as PARTES do instrumento ----
                    # O site exibe: PARTES <nome1> E <nome2>  (ou em linhas separadas)
                    partes_raw  = ""
                    m_partes = re.search(r'PARTES\s*(.+?)$', texto_norm, re.IGNORECASE | re.DOTALL)
                    if m_partes:
                        partes_raw = m_partes.group(1).strip()

                    # A 1ª parte é quem possui o CNPJ pesquisado (o empregador).
                    # A 2ª parte é a entidade sindical.
                    # Verifica se a 2ª parte é sindicato ou federação.
                    # Basta que QUALQUER parte seja sindicato/federação para validar,
                    # já que o CNPJ garante que a outra é a empresa buscada.
                    segunda_parte_ok = e_sindicato_ou_federacao(partes_raw if partes_raw else texto_norm)

                    motivo_rejeicao = ""
                    if not is_tipo_valido:
                        motivo_rejeicao = f"tipo invalido ('{tipo_raw}')"
                    elif not segunda_parte_ok:
                        motivo_rejeicao = "2a parte nao e sindicato/federacao (parece empresa)"

                    print(f"\n  [Pág {num_pagina} / Linha {i}] "
                          f"tipo_ok={is_tipo_valido} ('{tipo_raw}') | "
                          f"sind_fed_ok={segunda_parte_ok}")

                    if motivo_rejeicao:
                        print(f"    IGNORADO: {motivo_rejeicao}")
                        print(f"    Texto: {texto_norm[:250]}")
                        continue

                    achou_match = True
                    print(f"  [MATCH] Pág {num_pagina} / Linha {i}. Baixando...")

                    # Data de início de vigência
                    inicio_vigencia = "DATA_DESCONHECIDA"
                    m_data = re.search(r'(\d{2}/\d{2}/\d{4})', texto_linha)
                    if m_data:
                        inicio_vigencia = m_data.group(1).replace('/', '-')

                    tipo_arq      = "TA-CCT" if "TERMO ADITIVO" in tipo_check else "CCT"

                    # Busca o código do sindicato na tabela sindicatosistema.xlsx
                    codigo_sind = mapa_codigo.get(cnpj_digits, "")
                    prefixo     = f"{codigo_sind}-" if codigo_sind else ""

                    nome_esperado = formatar_nome_arquivo(
                        f"{prefixo}{tipo_arq}", sindicato_esperado, inicio_vigencia
                    )

                    # Verifica se já existe
                    ja_existe = any(
                        os.path.exists(os.path.join(DOWNLOAD_DIR, f"{nome_esperado}{ext}"))
                        for ext in ['.pdf', '.doc', '.docx']
                    )
                    if ja_existe:
                        print(f"  [PULANDO] Arquivo já existe: {nome_esperado}")
                        rel_ja_baixados.append((cnpj_formatado, sindicato_esperado, nome_esperado))
                        continue

                    limpar_temp()

                    # Clica no link de download
                    try:
                        link = linha.find_element(By.TAG_NAME, "a")
                        driver.execute_script("arguments[0].click();", link)
                    except Exception as e:
                        print(f"  [ERRO] Clique no link: {e}")
                        continue

                    # Aguarda nova janela
                    try:
                        WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > 1)
                        for h in driver.window_handles:
                            if h != janela_original:
                                driver.switch_to.window(h)
                                break
                        print("  Nova janela aberta. Aguardando download...")
                        time.sleep(2)
                        try:
                            btn_dl = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH,
                                    "//*[contains(translate(text(),'DOWNLOAD','download'),'download')] | "
                                    "//input[contains(translate(@value,'DOWNLOAD','download'),'download')]"
                                ))
                            )
                            btn_dl.click()
                        except:
                            pass
                    except:
                        print("  Sem nova janela — download pode ser direto.")

                    arq_baixado = aguardar_download(TEMP_DL_DIR, timeout=40)
                    if arq_baixado:
                        ext_arq = os.path.splitext(arq_baixado)[1].lower()
                        destino  = os.path.join(DOWNLOAD_DIR, f"{nome_esperado}{ext_arq}")
                        if os.path.exists(destino):
                            os.remove(destino)
                        shutil.move(arq_baixado, destino)
                        print(f"  [OK] Salvo: {nome_esperado}{ext_arq}")

                        # Converte .doc/.docx para PDF imediatamente
                        if ext_arq in ('.doc', '.docx'):
                            destino_final = converter_para_pdf(destino)
                        else:
                            destino_final = destino

                        nome_final = os.path.basename(destino_final)
                        rel_baixados.append((cnpj_formatado, sindicato_esperado, nome_final))
                    else:
                        print("  [AVISO] Arquivo não capturado em 40s.")
                        rel_nao_encontrados.append((cnpj_formatado, sindicato_esperado))

                except Exception as e:
                    print(f"  [ERRO] Pág {num_pagina} / Linha {i}: {e}")
                finally:
                    # Fecha janelas extras e volta para a principal
                    for h in driver.window_handles:
                        if h != janela_original:
                            try:
                                driver.switch_to.window(h)
                                driver.close()
                            except:
                                pass
                    try:
                        driver.switch_to.window(janela_original)
                    except:
                        pass

            # ---- Verifica se existe próxima página ----
            # O MTE usa links/botões de paginação com texto "Próxima", ">" ou número de página
            try:
                # Estratégias de localização do botão "Próxima página"
                btn_proxima = None

                # Tenta 1: link com texto ">" ou "Próxima" ou "proxima"
                candidatos = driver.find_elements(By.XPATH,
                    "//*[@id='divConsultaDetalhada']//a[contains(normalize-space(text()),'>')] | "
                    "//*[@id='divConsultaDetalhada']//a[contains(translate(normalize-space(text()),"
                    "'PRÓXIMAPRÓXIMA','proximaproximA'),'proxima')] | "
                    "//*[@id='divConsultaDetalhada']//input[contains(translate(@value,"
                    "'PRÓXIMA','proxima'),'proxima')]"
                )

                # Filtra apenas visíveis e habilitados
                for cand in candidatos:
                    if cand.is_displayed() and cand.is_enabled():
                        # Ignora se o botão/link estiver desabilitado via classe ou atributo
                        cls  = cand.get_attribute("class") or ""
                        aria = cand.get_attribute("aria-disabled") or ""
                        if "disabled" not in cls.lower() and aria.lower() != "true":
                            btn_proxima = cand
                            break

                # Tenta 2: link com número da próxima página
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
                    print(f"\n  [PAGINAÇÃO] Avançando para a página {num_pagina}...")
                    driver.execute_script("arguments[0].click();", btn_proxima)
                    # Aguarda a tabela recarregar
                    time.sleep(3)
                    try:
                        WebDriverWait(driver, 15).until(
                            EC.visibility_of_element_located((By.ID, "divExibirConsultaDetalhada"))
                        )
                    except:
                        pass
                else:
                    print(f"  [PAGINAÇÃO] Sem próxima página. Total de páginas lidas: {num_pagina}.")
                    break

            except Exception as e:
                print(f"  [PAGINAÇÃO] Erro ao verificar próxima página: {e}")
                break

        if not achou_match:
            print("  [SEM MATCH] Nenhuma linha passou em todos os critérios para este CNPJ.")
            rel_nao_encontrados.append((cnpj_formatado, sindicato_esperado))

    driver.quit()
    print("\n" + "="*60)
    print("Processamento finalizado!")
    print(f"Arquivos salvos em: {DOWNLOAD_DIR}")
    print("="*60)

    # ==========================================
    # GERAR RELATÓRIO TXT
    # ==========================================
    from datetime import datetime
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    relatorio_path = os.path.join(BASE_DIR, "busca CCT.txt")

    linhas_rel = []
    linhas_rel.append("=" * 70)
    linhas_rel.append("RELATÓRIO DE BUSCA - CONVENÇÕES COLETIVAS DE TRABALHO")
    linhas_rel.append(f"Gerado em: {agora}")
    linhas_rel.append("=" * 70)
    linhas_rel.append("")

    # --- Seção 1: Não encontrados ---
    linhas_rel.append("-" * 70)
    linhas_rel.append(f"1. NÃO ENCONTRADOS ({len(rel_nao_encontrados)} registro(s))")
    linhas_rel.append("-" * 70)
    if rel_nao_encontrados:
        for cnpj_r, sind_r in rel_nao_encontrados:
            linhas_rel.append(f"  CNPJ: {cnpj_r}")
            linhas_rel.append(f"  Sindicato: {sind_r}")
            linhas_rel.append("")
    else:
        linhas_rel.append("  Nenhum.")
        linhas_rel.append("")

    # --- Seção 2: Já baixados anteriormente ---
    linhas_rel.append("-" * 70)
    linhas_rel.append(f"2. JÁ BAIXADOS ANTERIORMENTE ({len(rel_ja_baixados)} registro(s))")
    linhas_rel.append("-" * 70)
    if rel_ja_baixados:
        for cnpj_r, sind_r, arq_r in rel_ja_baixados:
            linhas_rel.append(f"  CNPJ: {cnpj_r}")
            linhas_rel.append(f"  Sindicato: {sind_r}")
            linhas_rel.append(f"  Arquivo: {arq_r}")
            linhas_rel.append("")
    else:
        linhas_rel.append("  Nenhum.")
        linhas_rel.append("")

    # --- Seção 3: Baixados com sucesso nesta execução ---
    linhas_rel.append("-" * 70)
    linhas_rel.append(f"3. ENCONTRADOS E BAIXADOS ({len(rel_baixados)} registro(s))")
    linhas_rel.append("-" * 70)
    if rel_baixados:
        for cnpj_r, sind_r, arq_r in rel_baixados:
            linhas_rel.append(f"  CNPJ: {cnpj_r}")
            linhas_rel.append(f"  Sindicato: {sind_r}")
            linhas_rel.append(f"  Arquivo: {arq_r}")
            linhas_rel.append("")
    else:
        linhas_rel.append("  Nenhum.")
        linhas_rel.append("")

    linhas_rel.append("=" * 70)
    linhas_rel.append(f"RESUMO: {len(rel_baixados)} baixado(s) | {len(rel_ja_baixados)} já existia(m) | {len(rel_nao_encontrados)} não encontrado(s)")
    linhas_rel.append("=" * 70)

    with open(relatorio_path, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas_rel))

    print(f"\nRelatório salvo em: {relatorio_path}")

if __name__ == "__main__":
    processar_mediador()
