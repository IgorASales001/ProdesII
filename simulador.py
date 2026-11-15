# SO PARA TESTAR O BACKEND sem o ESP32. Publica leituras falsas, incluindo
# duas absurdas de proposito, para provar que o filtro as descarta.

import json
import time

import paho.mqtt.client as mqtt

import config

leituras = [
    {"temperatura": 25.1, "umidade": 60.0, "luz": 300, "chuva": 4095, "gas": 120, "pressao": 925.4},
    {"temperatura": 25.3, "umidade": 60.4, "luz": 310, "chuva": 4095, "gas": 118, "pressao": 925.4},
    {"temperatura": 25.2, "umidade": 61.0, "luz": 305, "chuva": 4095, "gas": 125, "pressao": 925.4},
    {"temperatura": 150.0, "umidade": 61.0, "luz": 305, "chuva": 4095, "gas": 125, "pressao": 925.4},   # absurda
    {"temperatura": 25.6, "umidade": 62.0, "luz": 3600, "chuva": 2100, "gas": 130, "pressao": 925.4},
    {"temperatura": 25.7, "umidade": 120.0, "luz": 3600, "chuva": 2100, "gas": 130, "pressao": 925.4},  # absurda
    {"temperatura": 25.8, "umidade": 85.0, "luz": 3600, "chuva": 2100, "gas": 500, "pressao": 925.4},   # alertas
]

cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
cliente.connect(config.BROKER, config.PORTA)
cliente.loop_start()
for leitura in leituras:
    cliente.publish(config.TOPICO, json.dumps(leitura))
    print("Enviado:", leitura)
    time.sleep(2)
time.sleep(1)
cliente.loop_stop()
cliente.disconnect()
