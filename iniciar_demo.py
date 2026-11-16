# Inicia a demonstracao com UM comando: backend, dashboard e (se instalado) o tunel publico.
# Uso (na pasta servidor):  python iniciar_demo.py   ou clique duas vezes em iniciar_demo.bat

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

PASTA = os.path.dirname(os.path.abspath(__file__))
PORTA_WEB = 8000
ARQUIVO_ACESSO = os.path.join(PASTA, "acesso.json")
PADRAO_URL = re.compile(r"https://([a-z0-9-]+)\.trycloudflare\.com")


def salvar_acesso(url):
    with open(ARQUIVO_ACESSO, "w", encoding="utf-8") as f:
        json.dump({"publico": url}, f)


def vigiar_tunel(processo):
    """Le a saida do cloudflared, acha o link publico e o grava em acesso.json."""
    for linha in processo.stderr:
        achado = PADRAO_URL.search(linha)
        if achado and achado.group(1) != "api":
            url = achado.group(0)
            salvar_acesso(url)
            print(f"\n=== LINK PUBLICO (provisorio): {url} ===\n", flush=True)


def main():
    salvar_acesso(None)  # apaga o link da execucao anterior
    processos = []
    try:
        processos.append(subprocess.Popen([sys.executable, "backend.py"], cwd=PASTA))
        processos.append(subprocess.Popen([sys.executable, "dashboard.py"], cwd=PASTA))
        exe = shutil.which("cloudflared")
        if exe:
            tunel = subprocess.Popen(
                [exe, "tunnel", "--url", f"http://localhost:{PORTA_WEB}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace")
            processos.append(tunel)
            threading.Thread(target=vigiar_tunel, args=(tunel,), daemon=True).start()
        else:
            print("cloudflared nao encontrado: so havera acesso local e pela rede Wi-Fi.")
        time.sleep(2)
        webbrowser.open(f"http://localhost:{PORTA_WEB}")
        print("Demonstracao no ar. Pressione Ctrl+C para encerrar tudo.")
        avisados = set()
        while True:
            time.sleep(1)
            for p in processos[:2]:
                if p.poll() is not None and p.pid not in avisados:
                    avisados.add(p.pid)
                    print("ATENCAO: um dos programas parou. Veja a mensagem de erro acima.")
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        for p in processos:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
