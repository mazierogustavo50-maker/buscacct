import os
import win32com.client
import time

def convert_doc_to_pdf(folder_path):
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    
    # Get absolute path for the folder
    abs_folder_path = os.path.abspath(folder_path)
    
    files = [f for f in os.listdir(abs_folder_path) if f.lower().endswith(".doc") or f.lower().endswith(".docx")]
    
    if not files:
        print("Nenhum arquivo .doc ou .docx encontrado.")
        word.Quit()
        return

    for file_name in files:
        file_path = os.path.join(abs_folder_path, file_name)
        pdf_name = os.path.splitext(file_name)[0] + ".pdf"
        pdf_path = os.path.join(abs_folder_path, pdf_name)
        
        if os.path.exists(pdf_path):
            print(f"Pulando {file_name}, PDF já existe.")
            continue
            
        print(f"Convertendo {file_name} para PDF...")
        try:
            doc = word.Documents.Open(file_path)
            # wdFormatPDF = 17
            doc.SaveAs(pdf_path, FileFormat=17)
            doc.Close()
            print(f"Sucesso: {pdf_name}")
            
            # Remover o arquivo original após a conversão
            try:
                os.remove(file_path)
                print(f"Arquivo original removido: {file_name}")
            except Exception as re:
                print(f"Erro ao remover arquivo original {file_name}: {re}")
        except Exception as e:
            print(f"Erro ao converter {file_name}: {e}")
            
    word.Quit()

if __name__ == "__main__":
    convencoes_dir = "convencoes"
    if os.path.exists(convencoes_dir):
        convert_doc_to_pdf(convencoes_dir)
    else:
        print(f"Diretório {convencoes_dir} não encontrado.")
