import time, os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

options = webdriver.ChromeOptions()
options.add_argument('--headless')
prefs = {
    'profile.default_content_settings.popups': 0,
    'download.default_directory': os.path.abspath('temp_dl')
}
options.add_experimental_option('prefs', prefs)

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
linha = linhas[2]
links = linha.find_elements(By.TAG_NAME, 'a')
print('Clicking:', links[0].get_attribute('outerHTML'))
janela_original = driver.current_window_handle
driver.execute_script('arguments[0].click();', links[0])
time.sleep(5)

print('Handles count:', len(driver.window_handles))
if len(driver.window_handles) > 1:
    driver.switch_to.window(driver.window_handles[-1])
    print('New window URL:', driver.current_url)
    print('New window source length:', len(driver.page_source))
    if 'DOWNLOAD' in driver.page_source.upper() or 'IMPRIMIR' in driver.page_source.upper():
        print('Found download/print buttons!')
        
driver.quit()