import network
import time
import json
import struct
import machine
import ubinascii
import dht
from machine import Pin, ADC, I2C
from umqtt.simple import MQTTClient

WIFI_SSID = "NOME_DA_REDE"
WIFI_SENHA = "SENHA_DA_REDE"
TOPICO = "estacao68f3/estacaometeorologicaLIA2000/telemetria"  

BROKER = "broker.hivemq.com"
INTERVALO = 5  
CLIENT_ID = b"esp32-" + ubinascii.hexlify(machine.unique_id())

# SENSORES
sensor_dht = dht.DHT22(Pin(4))


def criar_adc(pino):
    adc = ADC(Pin(pino))
    adc.atten(ADC.ATTN_11DB) 
    return adc


adc_luz = criar_adc(34)
adc_chuva = criar_adc(35)
adc_gas = criar_adc(32)


DEBOUNCE_MS = 100
pulsos = 0
ultimo_pulso = 0
pino_pluviometro = Pin(13, Pin.IN, Pin.PULL_UP)


def contar_pulso(pino):
    global pulsos, ultimo_pulso
    agora = time.ticks_ms()
    if time.ticks_diff(agora, ultimo_pulso) > DEBOUNCE_MS:
        pulsos += 1
        ultimo_pulso = agora


pino_pluviometro.irq(trigger=Pin.IRQ_FALLING, handler=contar_pulso)


# BMP280 (pressao atmosferica, I2C)
class BMP280:
    """Driver minimo: le temperatura e pressao pelo I2C."""

    def __init__(self, i2c, endereco):
        self.i2c = i2c
        self.addr = endereco
        self.chip_id = self.i2c.readfrom_mem(self.addr, 0xD0, 1)[0]
        if self.chip_id not in (0x56, 0x57, 0x58, 0x60):  # BMP280
            raise OSError("chip inesperado: 0x%02X" % self.chip_id)
        self.i2c.writeto_mem(self.addr, 0xE0, b"\xB6")  # reset
        time.sleep_ms(10)
        (self.t1, self.t2, self.t3, self.p1, self.p2, self.p3, self.p4,
         self.p5, self.p6, self.p7, self.p8, self.p9) = struct.unpack(
            "<HhhHhhhhhhhh", self.i2c.readfrom_mem(self.addr, 0x88, 24))
        self.i2c.writeto_mem(self.addr, 0xF5, b"\x08")  # filtro IIR x4
        self.i2c.writeto_mem(self.addr, 0xF4, b"\x57")  # temp x2, pressao x16, modo normal
        time.sleep_ms(50)

    def ler(self):
        """Retorna (temperatura em C, pressao em hPa) ou None se a leitura nao estiver pronta."""
        d = self.i2c.readfrom_mem(self.addr, 0xF7, 6)
        adc_p = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
        adc_t = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)
        if adc_p == 0x80000 or adc_t == 0x80000:
            return None
        return self._compensar(adc_t, adc_p)

    def _compensar(self, adc_t, adc_p):
        # Formulas de compensacao do datasheet da Bosch (inteiros)
        v1 = (((adc_t >> 3) - (self.t1 << 1)) * self.t2) >> 11
        v2 = (((((adc_t >> 4) - self.t1) * ((adc_t >> 4) - self.t1)) >> 12) * self.t3) >> 14
        t_fine = v1 + v2
        temperatura = ((t_fine * 5 + 128) >> 8) / 100

        v1 = t_fine - 128000
        v2 = v1 * v1 * self.p6
        v2 = v2 + ((v1 * self.p5) << 17)
        v2 = v2 + (self.p4 << 35)
        v1 = ((v1 * v1 * self.p3) >> 8) + ((v1 * self.p2) << 12)
        v1 = (((1 << 47) + v1) * self.p1) >> 33
        if v1 == 0:
            return temperatura, 0
        p = 1048576 - adc_p
        p = (((p << 31) - v2) * 3125) // v1
        v1 = (self.p9 * (p >> 13) * (p >> 13)) >> 25
        v2 = (self.p8 * p) >> 19
        p = ((p + v1 + v2) >> 8) + (self.p7 << 4)
        return temperatura, p / 256 / 100  # Pa -> hPa


i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=100000)
sensor_pressao = None


def iniciar_bmp280():
    """Procura o BMP280 nos enderecos 0x76/0x77. Se nao achar, segue sem ele."""
    global sensor_pressao
    sensor_pressao = None
    try:
        achados = i2c.scan()
        for endereco in (0x76, 0x77):
            if endereco in achados:
                sensor_pressao = BMP280(i2c, endereco)
                print("BMP280 encontrado em", hex(endereco))
                return
        print("BMP280 nao encontrado no I2C")
    except OSError as erro:
        print("BMP280 indisponivel:", erro)


def ler_pressao():
    """Pressao em hPa, ou None se o sensor nao responder."""
    global sensor_pressao
    try:
        if sensor_pressao is None:
            iniciar_bmp280()
        if sensor_pressao is None:
            return None
        medida = sensor_pressao.ler()
        if medida is None:
            return None
        return round(medida[1], 2)
    except OSError as erro:
        print("Falha no BMP280:", erro)
        sensor_pressao = None
        return None


def ler_sensores():
    """Retorna um dicionario com as leituras, ou None se o DHT22 falhar."""
    try:
        sensor_dht.measure()
        temperatura = sensor_dht.temperature()
        umidade = sensor_dht.humidity()
    except OSError:
        print("Falha ao ler o DHT22")
        return None
    return {
        "temperatura": temperatura,
        "umidade": umidade,
        "luz": adc_luz.read(),
        "chuva": adc_chuva.read(),
        "gas": adc_gas.read(),
        "pulsos": pulsos,
        "pressao": ler_pressao(),
    }


# REDE
def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Conectando ao Wi-Fi...")
        wlan.connect(WIFI_SSID, WIFI_SENHA)
        tentativas = 0
        while not wlan.isconnected() and tentativas < 30:
            time.sleep(1)
            tentativas += 1
    if not wlan.isconnected():
        raise RuntimeError("Wi-Fi nao conectou")
    print("Wi-Fi conectado. IP:", wlan.ifconfig()[0])
    return wlan


def conectar_mqtt():
    cliente = MQTTClient(CLIENT_ID, BROKER, keepalive=60)
    cliente.connect()
    print("MQTT conectado ao broker", BROKER)
    return cliente


# MAIN
wlan = None
cliente = None

while True:
    try:
        if wlan is None or not wlan.isconnected():
            wlan = conectar_wifi()
            cliente = None
        if cliente is None:
            cliente = conectar_mqtt()

        leitura = ler_sensores()
        if leitura is not None:
            mensagem = json.dumps(leitura)
            cliente.publish(TOPICO.encode(), mensagem.encode())
            print("Enviado:", mensagem)
    except Exception as erro:
        print("Erro:", erro, "- tentando reconectar")
        cliente = None
    time.sleep(INTERVALO)

