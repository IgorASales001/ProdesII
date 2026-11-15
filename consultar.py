# Mostra no terminal o que esta gravado no banco

import sqlite3

import config

con = sqlite3.connect(config.BANCO)
total = con.execute("SELECT COUNT(*) FROM leitura").fetchone()[0]
print(f"Total de leituras gravadas: {total}\n")
print("ID | DATA/HORA           | TEMP  | MEDIA | UMID  | PRESSAO | LUZ  | CHUVA | GAS | ALERTA")
consulta = """SELECT id, data_hora, temperatura, temp_media, umidade, pressao, luz, chuva, gas, alerta
              FROM leitura ORDER BY id DESC LIMIT 10"""
for id_, dh, t, tm, u, pr, luz, ch, gas, al in con.execute(consulta):
    pr_txt = "--" if pr is None else f"{pr:.1f}"
    print(f"{id_:<2} | {dh} | {t:<5} | {tm:<5} | {u:<5} | {pr_txt:<7} | {luz:<4} | {ch:<5} | {gas:<3} | {al}")
con.close()
