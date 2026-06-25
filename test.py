import time, os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

options = webdriver.ChromeOptions()
options.add_argument('--headless')
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)
driver.get('https://www3.mte.gov.br/sistemas/mediador/ConsultarInstColetivo')
time.sleep(2)

driver.execute_script('arguments[0].click();', driver.find_element(By.ID, 'chkNRCNPJ'))
driver.find_element(By.ID, 'txtNRCNPJ').send_keys('80622202000104')
Select(driver.find_element(By.ID, 'cboSTVigencia')).select_by_value('1')
driver.find_element(By.ID, 'btnPesquisar').click()

WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.ID, 'divExibirConsultaDetalhada')))

linhas = driver.find_elements(By.XPATH, "//*[@id='grdInstrumentos']//table[contains(@class, 'Dados')]//tr[@indice]")
print(f'Encontradas {len(linhas)} linhas.')
for idx, linha in enumerate(linhas):
    texto = linha.text
    print(f'Linha {idx}: {texto[:100]}...')
driver.quit()