# Servidor do dashboard: le o banco SQLite e entrega a pagina web.
# Rodar na mesma pasta do backend.py e do estacao.db:  python dashboard.py
# Depois abrir no navegador:  http://localhost:8000

import io
import json
import os
import socket
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import config

PASTA = os.path.dirname(os.path.abspath(__file__))
PORTA_WEB = 8000


def consultar():
    vazio = {"estacao": None, "ultima": None, "historico": []}
    try:
        con = sqlite3.connect(os.path.join(PASTA, config.BANCO))
        con.row_factory = sqlite3.Row
        estacao = con.execute(
            "SELECT nome, latitude, longitude FROM estacao WHERE id = 1").fetchone()
        linhas = con.execute(
            """SELECT data_hora, temperatura, umidade, luz, chuva, gas,
                      temp_media, umid_media, alerta, pulsos, chuva_mm,
                      pressao, press_media
               FROM leitura ORDER BY id DESC LIMIT 60""").fetchall()
        con.close()
    except sqlite3.Error:
        return vazio
    historico = [dict(l) for l in reversed(linhas)]
    return {
        "estacao": dict(estacao) if estacao else None,
        "ultima": historico[-1] if historico else None,
        "historico": historico,
    }


def ip_da_rede():
    """IP do computador na rede local (sem enviar nenhum pacote)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def acesso():
    """Links para abrir o dashboard: publico (escrito pelo iniciar_demo.py) e rede local."""
    publico = None
    try:
        with open(os.path.join(PASTA, "acesso.json"), encoding="utf-8") as f:
            publico = json.load(f).get("publico")
    except (OSError, ValueError):
        pass
    return {"publico": publico, "rede_local": f"http://{ip_da_rede()}:{PORTA_WEB}"}


def qr_svg(texto):
    import qrcode
    import qrcode.image.svg
    imagem = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage,
                         box_size=10, border=2)
    buffer = io.BytesIO()
    imagem.save(buffer)
    return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    def responder(self, corpo, tipo):
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/dados":
            self.responder(json.dumps(consultar()).encode("utf-8"),
                           "application/json; charset=utf-8")
        elif url.path == "/api/acesso":
            self.responder(json.dumps(acesso()).encode("utf-8"),
                           "application/json; charset=utf-8")
        elif url.path == "/qr.svg":
            alvo = parse_qs(url.query).get("alvo", ["local"])[0]
            dados = acesso()
            destino = dados["publico"] if alvo == "publico" else dados["rede_local"]
            try:
                if not destino:
                    raise ValueError("sem link")
                self.responder(qr_svg(destino), "image/svg+xml")
            except (ImportError, ValueError):
                self.send_error(404)
        elif url.path in ("/", "/index.html"):
            with open(os.path.join(PASTA, "dashboard.html"), "rb") as f:
                self.responder(f.read(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass  # silencia o log de cada requisicao


if __name__ == "__main__":
    servidor = ThreadingHTTPServer(("0.0.0.0", PORTA_WEB), Handler)
    print(f"Dashboard no ar: http://localhost:{PORTA_WEB}  (Ctrl+C para parar)")
    print(f"Na mesma rede Wi-Fi: http://{ip_da_rede()}:{PORTA_WEB}")
    servidor.serve_forever()
