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
# ESPN devuelve 403 en algunas de sus direcciones segun de donde salga el
# pedido. Con la tabla de posiciones paso lo mismo: la unica que respondio fue
# la de site.web.api con region e idioma. Se prueban en ese orden.
PATRONES = [
    "https://site.web.api.espn.com/apis/site/v2/sports/soccer/arg.2/scoreboard?region=ar&lang=es&dates={d}",
    "https://site.api.espn.com/apis/site/v2/sports/soccer/arg.2/scoreboard?region=ar&lang=es&dates={d}",
    "https://site.web.api.espn.com/apis/site/v2/sports/soccer/arg.2/scoreboard?dates={d}",
    "https://site.api.espn.com/apis/site/v2/sports/soccer/arg.2/scoreboard?dates={d}",
]

# Las mismas cabeceras que usa el scraper de la tabla, pero apuntando a la
# pagina de resultados: ESPN mira el Referer.
CABECERAS = dict(A.CABECERAS)
CABECERAS["Referer"] = "https://www.espn.com.ar/futbol/resultados/_/liga/arg.2"

PATRON_OK = None      # la primera direccion que responde se reusa para el resto
MARGEN_HS = 3          # no pedir un dia hasta 3 horas despues de terminado
MAX_DIAS = 45          # tope de consultas por corrida


def pedir(url):
    req = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(req, timeout=25) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        return json.loads(r.read().decode())


def bajar(dia):
    """dia en formato YYYYMMDD. Devuelve la lista de eventos de ESPN.

    La primera vez prueba todas las direcciones; despues reusa la que anduvo.
    """
    global PATRON_OK
    if PATRON_OK:
        return pedir(PATRON_OK.format(d=dia)).get('events') or []

    fallos = []
    for pat in PATRONES:
        try:
            datos = pedir(pat.format(d=dia))
        except urllib.error.HTTPError as ex:
            fallos.append(f"{pat.split('?')[0]} → HTTP {ex.code}")
            continue
        except Exception as ex:
            fallos.append(f"{pat.split('?')[0]} → {type(ex).__name__}")
            continue
        PATRON_OK = pat
        print(f"  responde: {pat.split('?')[0]}")
        return datos.get('events') or []
    raise RuntimeError("ninguna direccion respondio: " + " · ".join(fallos))


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
    # Se barre un RANGO de dias, no solo los que figuran en el fixture.
    # El fixture sembrado tenia un dia por fecha, pero la categoria juega de
    # viernes a lunes y ademas hay reprogramaciones. Buscar cada partido solo
    # en su dia programado hacia que no se encontrara nunca.
    pend = [p['fecha'] for p in partidos if p['gl'] is None]
    if not pend:
        print('no quedan partidos pendientes')
        return 0

    # De donde arranca el barrido. Si ya se barrio antes, se sigue desde ahi
    # pero repasando los ultimos dias: ESPN a veces carga un resultado tarde.
    # Sin ese tope, cada corrida volveria a pedir toda la temporada.
    REPASO = 7
    desde = d.get('escaneado_hasta')
    if desde:
        arranque = (datetime.date.fromisoformat(desde) -
                    datetime.timedelta(days=REPASO)).isoformat()
    else:
        arranque = min(pend)

    # Partidos que ya deberian haberse jugado y siguen sin resultado: si quedan
    # muchos, algo no esta funcionando y conviene que se vea en el log.
    viejos = [p for p in partidos
              if p['gl'] is None and p['fecha'] < arranque]
    if viejos:
        print(f'AVISO: {len(viejos)} partido(s) pendientes anteriores al barrido:')
        for p in viejos[:5]:
            print(f"   {p['fecha']}  {A.CLUBES[p['local']][0]} vs {A.CLUBES[p['visita']][0]}")
        if len(viejos) > 5:
            print(f'   ...y {len(viejos)-5} mas')
        # se los vuelve a buscar desde su fecha, por si fueron reprogramados
        arranque = min(arranque, min(p['fecha'] for p in viejos))

    dias = []
    f = datetime.date.fromisoformat(arranque)
    tope = datetime.date.fromisoformat(limite)
    while f <= tope and len(dias) < MAX_DIAS:
        dias.append(f.isoformat())
        f += datetime.timedelta(days=1)
    if not dias:
        print('no hay dias nuevos para consultar')
        return 0

    print(f'barriendo {len(dias)} dia(s): del {dias[0]} al {dias[-1]}')
    nuevos, problemas = 0, []

    # Un cruce (local, visitante) es unico en toda la temporada, asi que se
    # puede emparejar por equipos sin depender de la fecha programada.
    pendientes = {(p['local'], p['visita']): p for p in partidos if p['gl'] is None}
    ultimo_ok = None

    for dia in dias:
        clave = dia.replace('-', '')
        try:
            eventos = bajar(clave)
        except Exception as ex:
            problemas.append(f'{dia}: {type(ex).__name__} {ex}')
            # Si ninguna direccion responde, el problema no es ese dia: es el
            # acceso. No tiene sentido repetir el mismo error en cada dia.
            if PATRON_OK is None:
                print('ABORTA: ESPN no responde en ninguna direccion.')
                print('  ' + str(ex))
                return 1
            continue
        time.sleep(0.6)   # no apurar a ESPN
        ultimo_ok = dia

        for ev in eventos:
            m = marcador(ev)
            if not m:
                continue
            loc, gl, vis, gv = m
            p = pendientes.get((loc, vis))
            if p is None:
                continue            # ya cargado, o un partido que no es de este torneo
            if not (0 <= gl <= 15 and 0 <= gv <= 15):
                problemas.append(f"{dia} {loc}-{vis}: marcador raro {gl}-{gv}")
                continue
            reprogramado = '' if p['fecha'] == dia else f"  (estaba para el {p['fecha']})"
            p['gl'], p['gv'] = gl, gv
            p['fecha'] = dia        # la fecha real, no la programada
            del pendientes[(loc, vis)]
            nuevos += 1
            print(f"  {dia}  {A.CLUBES[loc][0]} {gl}-{gv} {A.CLUBES[vis][0]}{reprogramado}")

    if problemas:
        print('problemas:')
        for x in problemas:
            print('  -', x)

    if not nuevos:
        # se guarda hasta donde se barrio, asi la proxima corrida no repite
        if ultimo_ok and ultimo_ok != d.get('escaneado_hasta'):
            d['escaneado_hasta'] = ultimo_ok
            json.dump(d, open(ARCHIVO, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=0)
            print(f'sin resultados nuevos · barrido hasta {ultimo_ok}')
        else:
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

    if ultimo_ok:
        d['escaneado_hasta'] = ultimo_ok
    d['actualizado'] = ahora.isoformat(timespec='seconds')
    d['jugados'] = len(jug)
    d['pendientes'] = len(partidos) - len(jug)
    json.dump(d, open(ARCHIVO, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    open(SENAL, 'w').close()     # el workflow lo busca para recalcular el modelo
    print(f'OK · {nuevos} resultado(s) nuevo(s) · {len(jug)} jugados de {len(partidos)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
