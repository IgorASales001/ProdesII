# Backend: escuta o MQTT, valida os dados (logica matematica),
# calcula media movel, gera alertas (algebra de Boole) e grava no SQLite.

import json
import sqlite3
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt

import config

# Regras de validacao 
# Proposicao de validade: um valor so e aceito se minimo <= valor <= maximo.
LIMITES = {
    "temperatura": (-40, 80),   # faixa do DHT22
    "umidade": (0, 100),
    "luz": (0, 4095),           # ADC de 12 bits do ESP32
    "chuva": (0, 4095),
    "gas": (0, 4095),
}
LIMITE_PRESSAO = (300, 1100)    # faixa do BMP280, em hPa
# Salto maximo aceito entre a leitura nova e a media recente (descarta picos).
SALTO_MAX = {"temperatura": 10, "umidade": 30}
SALTO_PRESSAO = 5               # hPa
JANELA = 5                      # quantidade de leituras na media movel
K_MM = 0.2794                   # mm de chuva por pulso (basculada) do pluviometro

historico = {
    "temperatura": deque(maxlen=JANELA),
    "umidade": deque(maxlen=JANELA),
    "pressao": deque(maxlen=JANELA),
}


def inicializar_banco():
    con = sqlite3.connect(config.BANCO)
    con.execute("""
        CREATE TABLE IF NOT EXISTS estacao (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS leitura (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            estacao_id INTEGER NOT NULL,
            data_hora TEXT NOT NULL,
            temperatura REAL,
            umidade REAL,
            luz INTEGER,
            chuva INTEGER,
            gas INTEGER,
            temp_media REAL,
            umid_media REAL,
            alerta TEXT,
            pulsos INTEGER,
            chuva_mm REAL,
            pressao REAL,
            press_media REAL,
            FOREIGN KEY (estacao_id) REFERENCES estacao(id)
        )""")
    # Bancos criados antes dos sensores novos ganham as colunas que faltam
    existentes = [c[1] for c in con.execute("PRAGMA table_info(leitura)")]
    for coluna, tipo in (("pulsos", "INTEGER"), ("chuva_mm", "REAL"),
                         ("pressao", "REAL"), ("press_media", "REAL")):
        if coluna not in existentes:
            con.execute(f"ALTER TABLE leitura ADD COLUMN {coluna} {tipo}")
    con.execute(
        """INSERT INTO estacao (id, nome, latitude, longitude) VALUES (1, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET nome = excluded.nome,
               latitude = excluded.latitude, longitude = excluded.longitude""",
        (config.ESTACAO_NOME, config.LATITUDE, config.LONGITUDE),
    )
    con.commit()
    con.close()


def valida(d):
    """Retorna (True, '') se a leitura e valida, senao (False, motivo)."""
    for campo, (minimo, maximo) in LIMITES.items():
        v = d.get(campo)
        if not isinstance(v, (int, float)):
            return False, f"{campo} ausente ou invalido ({v})"
        if not (minimo <= v <= maximo):
            return False, f"{campo}={v} fora do intervalo [{minimo}, {maximo}]"
    if "pulsos" in d:
        p = d["pulsos"]
        if not isinstance(p, int) or p < 0:
            return False, f"pulsos invalido ({p})"
    pressao = d.get("pressao")
    if pressao is not None:  # sem BMP280 a leitura vem vazia (null) e e aceita
        minimo, maximo = LIMITE_PRESSAO
        if not isinstance(pressao, (int, float)) or not (minimo <= pressao <= maximo):
            return False, f"pressao={pressao} fora do intervalo [{minimo}, {maximo}]"
        h = historico["pressao"]
        if h and abs(pressao - sum(h) / len(h)) > SALTO_PRESSAO:
            return False, f"pressao={pressao} variou mais que {SALTO_PRESSAO} hPa em relacao a media"
    for campo, salto in SALTO_MAX.items():
        h = historico[campo]
        if h and abs(d[campo] - sum(h) / len(h)) > salto:
            return False, f"{campo}={d[campo]} variou mais que {salto} em relacao a media"
    return True, ""


def alertas(d):
    """Regras de alerta com operadores logicos (AND, OR, NOT)."""
    molhado = d["chuva"] < 3000        # sensor de chuva: valor cai quando molha
    escuro = d["luz"] > 3000           # sensor de luz: valor sobe no escuro
    gas_alto = d["gas"] > 400
    calor = d["temperatura"] > 35
    umido = d["umidade"] > 80

    lista = []
    if molhado and escuro and umido:
        lista.append("TEMPESTADE")
    if gas_alto:
        lista.append("AR_RUIM")
    if calor and not molhado:
        lista.append("CALOR_EXTREMO")
    return ",".join(lista) if lista else "NENHUM"


def media(valores):
    return round(sum(valores) / len(valores), 2)


def processar(texto):
    """Recebe o JSON em texto, valida e grava. Retorna (gravou, mensagem)."""
    try:
        d = json.loads(texto)
    except json.JSONDecodeError:
        return False, "JSON invalido"

    ok, motivo = valida(d)
    if not ok:
        return False, "DESCARTADA: " + motivo

    historico["temperatura"].append(d["temperatura"])
    historico["umidade"].append(d["umidade"])
    temp_media = media(historico["temperatura"])
    umid_media = media(historico["umidade"])

    pressao = d.get("pressao")
    press_media = None
    if pressao is not None:
        historico["pressao"].append(pressao)
        press_media = media(historico["pressao"])

    alerta = alertas(d)
    pulsos = d.get("pulsos")
    chuva_mm = round(pulsos * K_MM, 2) if pulsos is not None else None

    con = sqlite3.connect(config.BANCO)
    con.execute(
        """INSERT INTO leitura
           (estacao_id, data_hora, temperatura, umidade, luz, chuva, gas,
            temp_media, umid_media, alerta, pulsos, chuva_mm, pressao, press_media)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(timespec="seconds"), d["temperatura"], d["umidade"],
         d["luz"], d["chuva"], d["gas"], temp_media, umid_media, alerta,
         pulsos, chuva_mm, pressao, press_media),
    )
    con.commit()
    con.close()
    return True, (f"GRAVADA: temp={d['temperatura']} (media {temp_media}) umid={d['umidade']} "
                  f"pressao={pressao} pulsos={pulsos} chuva_mm={chuva_mm} alerta={alerta}")


def on_connect(client, userdata, flags, reason_code, properties):
    print("Conectado ao broker. Codigo:", reason_code)
    client.subscribe(config.TOPICO)
    print("Escutando o topico:", config.TOPICO)


def on_message(client, userdata, msg):
    gravou, mensagem = processar(msg.payload.decode())
    print(mensagem)


if __name__ == "__main__":
    inicializar_banco()
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    cliente.on_connect = on_connect
    cliente.on_message = on_message
    cliente.connect(config.BROKER, config.PORTA)
    cliente.loop_forever()
