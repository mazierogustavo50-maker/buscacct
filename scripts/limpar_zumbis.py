#!/usr/bin/env python3
"""
Script utilitário para limpar processos zumbis do scraper (Chrome, chromedriver, python).
Rode manualmente quando a interface web não conseguir abortar uma execução.
"""
import os
import sys
import signal
import subprocess
import argparse


def matar_por_nome(nomes, confirmar=True):
    """Mata processos pelo nome (cross-platform: Windows via taskkill, Linux via pkill)."""
    sistema = sys.platform
    encontrados = []

    if sistema.startswith("win"):
        # Lista processos
        try:
            output = subprocess.check_output(["tasklist"], text=True, encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"[ERRO] Não foi possível listar processos: {e}")
            return

        for nome in nomes:
            for linha in output.splitlines():
                if nome.lower() in linha.lower():
                    partes = linha.split()
                    if len(partes) >= 2:
                        try:
                            pid = int(partes[1])
                            encontrados.append((nome, pid))
                        except ValueError:
                            pass
    else:
        for nome in nomes:
            try:
                output = subprocess.check_output(["pgrep", "-f", nome], text=True)
                for pid_str in output.strip().splitlines():
                    try:
                        pid = int(pid_str.strip())
                        encontrados.append((nome, pid))
                    except ValueError:
                        pass
            except subprocess.CalledProcessError:
                pass

    if not encontrados:
        print("Nenhum processo zumbi encontrado.")
        return

    print(f"\nProcessos encontrados: {len(encontrados)}")
    for nome, pid in encontrados:
        print(f"  - {nome} (PID {pid})")

    if confirmar:
        resposta = input("\nDeseja encerrar todos? [s/N]: ").strip().lower()
        if resposta not in ("s", "sim"):
            print("Cancelado.")
            return

    mortos = 0
    for nome, pid in encontrados:
        try:
            if sistema.startswith("win"):
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            print(f"  [OK] PID {pid} ({nome}) terminado.")
            mortos += 1
        except Exception as e:
            print(f"  [ERRO] PID {pid} ({nome}): {e}")

    print(f"\nResumo: {mortos}/{len(encontrados)} processo(s) encerrado(s).")


def limpar_temp(diretorios):
    """Remove arquivos temporários de download."""
    for d in diretorios:
        if not os.path.isdir(d):
            continue
        removidos = 0
        for item in os.listdir(d):
            caminho = os.path.join(d, item)
            try:
                if os.path.isfile(caminho):
                    os.remove(caminho)
                    removidos += 1
                elif os.path.isdir(caminho):
                    import shutil
                    shutil.rmtree(caminho)
                    removidos += 1
            except Exception as e:
                print(f"  [AVISO] Não foi possível remover {caminho}: {e}")
        if removidos:
            print(f"[OK] {removidos} item(s) removido(s) de {d}")
        else:
            print(f"[INFO] {d} já está vazio.")


def main():
    parser = argparse.ArgumentParser(description="Limpa processos zumbis do scraper e arquivos temporários.")
    parser.add_argument("--chrome", action="store_true", help="Mata processos chrome/chromedriver.")
    parser.add_argument("--python", action="store_true", help="Mata processos python do scraper.")
    parser.add_argument("--tudo", action="store_true", help="Mata chrome + chromedriver + python.")
    parser.add_argument("--temp", action="store_true", help="Limpa pasta temp_dl do projeto.")
    parser.add_argument("--yes", "-y", action="store_true", help="Não pede confirmação.")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_dirs = [os.path.join(base_dir, "temp_dl")]

    if args.tudo or args.chrome:
        print("\n=== Chrome / Chromedriver ===")
        matar_por_nome(["chrome.exe", "chromedriver.exe", "chrome", "chromedriver"], confirmar=not args.yes)

    if args.tudo or args.python:
        print("\n=== Python (scraper) ===")
        matar_por_nome(["python.exe", "python"], confirmar=not args.yes)

    if args.temp or args.tudo:
        print("\n=== Arquivos temporários ===")
        limpar_temp(temp_dirs)

    if not any([args.tudo, args.chrome, args.python, args.temp]):
        parser.print_help()


if __name__ == "__main__":
    main()
