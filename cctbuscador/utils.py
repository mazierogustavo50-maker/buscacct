import os
import sys
import subprocess
import time
from django.conf import settings


def iniciar_scraper_background(execucao, headless=True, forcar=False, sindicato_codigo=""):
    """
    Inicia o management command run_scraper em background via subprocess.
    Retorna (proc, log_path) ou levanta Exception em caso de falha imediata.
    """
    manage_py = os.path.join(settings.BASE_DIR, "manage.py")
    cmd = [sys.executable, manage_py, "run_scraper"]
    if headless:
        cmd.append("--headless")
    if forcar:
        cmd.append("--forcar")
    if sindicato_codigo:
        cmd.extend(["--sindicato-codigo", sindicato_codigo])
    cmd.extend(["--execucao-id", str(execucao.id)])

    env = os.environ.copy()
    env.setdefault("DJANGO_SETTINGS_MODULE", "buscacct.settings")

    # Arquivo de log para acompanhar erros de inicialização
    log_dir = os.path.join(settings.BASE_DIR, "data")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"scraper_{execucao.id}.log")

    log_file = open(log_path, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=settings.BASE_DIR,
            env=env,
        )
        execucao.pid = proc.pid
        execucao.save(update_fields=["pid"])

        # Verifica se o processo não morreu nos primeiros 5 segundos
        time.sleep(5)
        ret = proc.poll()
        if ret is not None:
            log_file.flush()
            log_file.close()
            with open(log_path, "r", encoding="utf-8") as f:
                erro_log = f.read().strip()
            raise RuntimeError(
                f"O processo do scraper morreu imediatamente (exit code {ret}).\n"
                f"Log: {erro_log[:500]}"
            )

        return proc, log_path
    except Exception:
        log_file.close()
        raise
