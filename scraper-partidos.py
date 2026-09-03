#!/usr/bin/env python3
"""
Completa los resultados de partidos.json consultando ESPN.

El fixture (quien juega contra quien y que dia) se sembro una sola vez desde
un CSV de FootyStats. Este script solo agrega los resultados que faltan.

Consulta unicamente los dias que ya pasaron y todavia no tienen resultado.
Un partido que ya se cargo no se vuelve a pedir nunca. En regimen normal son
una o dos consultas por semana.

Regla de oro, igual que en el resto del proyecto: si algo no cierra, no se
escribe nada. Es preferible quedarse sin el ultimo resultado que cargar uno mal.

Si carga resultados nuevos deja un archivo vacio llamado .hay-nuevos.
El workflow lo busca para decidir si vale la pena recalcular el modelo.
Se usa un archivo y no el codigo de salida porque un error real tambien
sale distinto de cero, y no queremos confundir "hubo novedades" con "fallo".
"""
import json, os, sys, datetime, urllib.request, urllib.error, time

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(AQUI, 'scraper'))
import actualizar as A

ARCHIVO = os.path.join(AQUI, 'partidos.json')
SENAL = os.path.join(AQUI, '.hay-nuevos')
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/arg.2/scoreboard?dates="
MARGEN_HS = 3          # no pedir un dia hasta 3 horas despues de terminado
MAX_DIAS = 20          # tope de consultas por corrida


def bajar(dia):
    """dia en formato YYYYMMDD. Devuelve la lista de eventos de ESPN."""
    req = urllib.request.Request(BASE + dia, headers=A.CABECERAS)
    with urllib.request.urlopen(req, timeout=25) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        return json.loads(r.read().decode()).get('events') or []


def marcador(ev):
    """Saca (id_local, goles_local, id_visita, goles_visita) de un evento.

    Devuelve None si el partido no termino o si algo no se entiende.
    """
    comp = (ev.get('competitions') or [None])[0]
    if not comp:
        return None
    est = ((comp.get('status') or {}).get('type') or {})
    if not est.get('completed'):
        return None            # todavia no termino: no se toca
    lados = comp.get('competitors') or []
    if len(lados) != 2:
        return None
    datos = {}
    for c in lados:
        nombre = ((c.get('team') or {}).get('displayName') or '')
        cid = A.a_id(nombre)
        if not cid or c.get('score') is None:
            return None
        datos[c.get('homeAway')] = (cid, int(c['score']))
    if 'home' not in datos or 'away' not in datos:
        return None
    return datos['home'][0], datos['home'][1], datos['away'][0], datos['away'][1]


def main():
    if os.path.exists(SENAL):
        os.remove(SENAL)
    if not os.path.exists(ARCHIVO):
        print('falta partidos.json: hay que sembrarlo una vez desde el CSV')
        return 1
    d = json.load(open(ARCHIVO, encoding='utf-8'))
    partidos = d['partidos']

    ahora = datetime.datetime.now(datetime.timezone.utc)
    limite = (ahora - datetime.timedelta(hours=MARGEN_HS)).strftime('%Y-%m-%d')

    # dias con partidos sin resultado que ya deberian haberse jugado
    dias = sorted({p['fecha'] for p in partidos
                   if p['gl'] is None and p['fecha'] <= limite})
    if not dias:
        print('no hay dias pendientes por consultar')
        return 0
    if len(dias) > MAX_DIAS:
        print(f'{len(dias)} dias pendientes, se consultan los {MAX_DIAS} mas viejos')
        dias = dias[:MAX_DIAS]

    print(f'consultando {len(dias)} dia(s): {", ".join(dias)}')
    nuevos, problemas = 0, []

    for dia in dias:
        clave = dia.replace('-', '')
        try:
            eventos = bajar(clave)
        except Exception as ex:
            problemas.append(f'{dia}: {type(ex).__name__} {ex}')
            continue
        time.sleep(1)   # no apurar a ESPN

        # resultados que ESPN reporta para ese dia
        vistos = {}
        for ev in eventos:
            m = marcador(ev)
            if m:
                vistos[(m[0], m[2])] = (m[1], m[3])

        for p in partidos:
            if p['fecha'] != dia or p['gl'] is not None:
                continue
            r = vistos.get((p['local'], p['visita']))
            if r is None:
                continue
            gl, gv = r
            if not (0 <= gl <= 15 and 0 <= gv <= 15):
                problemas.append(f"{dia} {p['local']}-{p['visita']}: marcador raro {gl}-{gv}")
                continue
            p['gl'], p['gv'] = gl, gv
            nuevos += 1
            print(f"  {dia}  {A.CLUBES[p['local']][0]} {gl}-{gv} {A.CLUBES[p['visita']][0]}")

    if problemas:
        print('problemas:')
        for x in problemas:
            print('  -', x)

    if not nuevos:
        print('sin resultados nuevos')
        return 0

    # controles antes de escribir
    jug = [p for p in partidos if p['gl'] is not None]
    cuenta = {}
    for p in jug:
        cuenta[p['local']] = cuenta.get(p['local'], 0) + 1
        cuenta[p['visita']] = cuenta.get(p['visita'], 0) + 1
    if len(cuenta) != 36:
        print(f'ABORTA: hay {len(cuenta)} equipos con partidos, deberian ser 36')
        return 1
    if max(cuenta.values()) - min(cuenta.values()) > 5:
        print(f'ABORTA: PJ muy dispares ({min(cuenta.values())} a {max(cuenta.values())})')
        return 1

    d['actualizado'] = ahora.isoformat(timespec='seconds')
    d['jugados'] = len(jug)
    d['pendientes'] = len(partidos) - len(jug)
    json.dump(d, open(ARCHIVO, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    open(SENAL, 'w').close()     # el workflow lo busca para recalcular el modelo
    print(f'OK · {nuevos} resultado(s) nuevo(s) · {len(jug)} jugados de {len(partidos)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
