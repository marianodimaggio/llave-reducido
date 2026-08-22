#!/usr/bin/env python3
"""
Baja la tabla de la Primera Nacional desde el endpoint publico de ESPN (arg.2),
la normaliza y la escribe en data.json.

Regla de oro: si algo no cierra, NO se pisa data.json.
Es preferible mostrar datos viejos con la fecha a la vista que datos nuevos y mal.
"""
import json, os, sys, time, unicodedata, urllib.request, urllib.error, datetime

URLS = [
    "https://site.api.espn.com/apis/v2/sports/soccer/arg.2/standings",
    "https://site.api.espn.com/apis/v2/sports/soccer/arg.2/standings?season=2026",
    "https://site.web.api.espn.com/apis/v2/sports/soccer/arg.2/standings?region=ar&lang=es&season=2026",
]

# ESPN rechaza los pedidos que no parecen venir de un navegador.
CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Referer": "https://www.espn.com.ar/futbol/posiciones/_/liga/arg.2",
    "Origin": "https://www.espn.com.ar",
    "Connection": "keep-alive",
}
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(RAIZ, "data.json")
ESTADO = os.path.join(RAIZ, "estado.json")
CORRECCIONES = os.path.join(RAIZ, "correcciones.json")
CAMPOS = ("pj", "pts", "gf", "gc")

# ---------------------------------------------------------------- clubes
# clave = id interno · valor = (nombre a mostrar, zona)
CLUBES = {
    # Zona A
    "ferro":       ("Ferro", "A"),
    "moron":       ("Dep. Morón", "A"),
    "losandes":    ("Los Andes", "A"),
    "colon":       ("Colón", "A"),
    "bolivar":     ("Cdad. de Bolívar", "A"),
    "estudiantesc":("Estudiantes (C)", "A"),
    "almirante":   ("Almirante Brown", "A"),
    "madryn":      ("Dep. Madryn", "A"),
    "godoy":       ("Godoy Cruz", "A"),
    "sanmiguel":   ("San Miguel", "A"),
    "defbelgrano": ("Def. de Belgrano", "A"),
    "racingcba":   ("Racing (Cba)", "A"),
    "allboys":     ("All Boys", "A"),
    "santelmo":    ("San Telmo", "A"),
    "centralnorte":("Central Norte", "A"),
    "acassuso":    ("Acassuso", "A"),
    "mitre":       ("Mitre (SdE)", "A"),
    "chacoforever":("Chaco For Ever", "A"),
    # Zona B
    "gimnasiaj":   ("Gimnasia (J)", "B"),
    "atlanta":     ("Atlanta", "B"),
    "tristan":     ("Tristán Suárez", "B"),
    "temperley":   ("Temperley", "B"),
    "maipu":       ("Dep. Maipú", "B"),
    "midland":     ("Midland", "B"),
    "rafaela":     ("At. Rafaela", "B"),
    "sanmartint":  ("San Martín (T)", "B"),
    "nuevachicago":("Nueva Chicago", "B"),
    "almagro":     ("Almagro", "B"),
    "quilmes":     ("Quilmes", "B"),
    "gyt":         ("Gimnasia y Tiro", "B"),
    "colegiales":  ("Colegiales", "B"),
    "sanmartinsj": ("San Martín (SJ)", "B"),
    "chacarita":   ("Chacarita", "B"),
    "patronato":   ("Patronato", "B"),
    "guemes":      ("Güemes", "B"),
    "agropecuario":("Agropecuario", "B"),
}

# como puede venir escrito el nombre en ESPN -> id interno
ALIAS = {
    "ferro carril oeste": "ferro", "ferro": "ferro",
    "deportivo moron": "moron", "moron": "moron",
    "los andes": "losandes",
    "colon": "colon", "club atletico colon": "colon", "colon de santa fe": "colon",
    "ciudad de bolivar": "bolivar", "ciudad bolivar": "bolivar",
    "estudiantes de buenos aires": "estudiantesc", "estudiantes bs as": "estudiantesc",
    "estudiantes caseros": "estudiantesc", "estudiantes": "estudiantesc",
    "almirante brown": "almirante",
    "deportivo madryn": "madryn", "madryn": "madryn",
    "godoy cruz antonio tomba": "godoy", "godoy cruz": "godoy",
    "san miguel": "sanmiguel",
    "defensores de belgrano": "defbelgrano",
    "racing de cordoba": "racingcba", "racing cordoba": "racingcba", "racing club de cordoba": "racingcba",
    "all boys": "allboys",
    "san telmo": "santelmo",
    "central norte": "centralnorte", "central norte salta": "centralnorte",
    "acassuso": "acassuso",
    "ca mitre": "mitre", "mitre": "mitre", "club atletico mitre": "mitre",
    "chaco for ever": "chacoforever", "chaco forever": "chacoforever",
    "gimnasia y esgrima jujuy": "gimnasiaj", "gimnasia jujuy": "gimnasiaj",
    "gimnasia y esgrima (j)": "gimnasiaj", "gimnasia de jujuy": "gimnasiaj",
    "atlanta": "atlanta",
    "tristan suarez": "tristan",
    "temperley": "temperley",
    "deportivo maipu": "maipu", "maipu": "maipu",
    "ferrocarril midland": "midland", "midland": "midland",
    "atletico rafaela": "rafaela", "atletico de rafaela": "rafaela",
    "san martin de tucuman": "sanmartint", "san martin tucuman": "sanmartint",
    "nueva chicago": "nuevachicago",
    "almagro": "almagro",
    "quilmes": "quilmes",
    "gimnasia y tiro": "gyt", "gimnasia y tiro (salta)": "gyt", "gimnasia y tiro salta": "gyt",
    "colegiales": "colegiales",
    "san martin de san juan": "sanmartinsj", "san martin san juan": "sanmartinsj",
    "chacarita juniors": "chacarita", "chacarita": "chacarita",
    "patronato": "patronato", "club atletico patronato": "patronato",
    "guemes": "guemes", "club atletico guemes": "guemes",
    "agropecuario": "agropecuario", "agropecuario argentino": "agropecuario",
    # formas que devuelve ESPN con la ciudad entre parentesis
    "colon santa fe": "colon",
    "estudiantes buenos aires": "estudiantesc",
    "mitre santiago del estero": "mitre",
    "gimnasia y esgrima jujuy": "gimnasiaj",
    "racing cordoba": "racingcba",
    "san martin san juan": "sanmartinsj",
    "san martin tucuman": "sanmartint",
    "central norte salta": "centralnorte",
    "gimnasia y tiro salta": "gyt",
    "defensores belgrano": "defbelgrano",
    "guemes santiago del estero": "guemes",
    "patronato parana": "patronato",
}

def pelar(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    # ESPN escribe "Colon (Santa Fe)", "San Martin (Tucuman)".
    # Sacamos parentesis y puntuacion para que un solo alias cubra las dos formas.
    for c in "().,-–—'\"":
        s = s.replace(c, " ")
    return " ".join(s.split())

def a_id(nombre):
    return ALIAS.get(pelar(nombre))

# ---------------------------------------------------------------- bajada
def bajar():
    """Prueba las direcciones en orden. Si todas fallan, cuenta que paso con cada una."""
    fallos = []
    for url in URLS:
        for intento in (1, 2):
            try:
                req = urllib.request.Request(url, headers=CABECERAS)
                with urllib.request.urlopen(req, timeout=25) as r:
                    if r.status != 200:
                        raise RuntimeError(f"HTTP {r.status}")
                    datos = json.loads(r.read().decode())
                print(f"  respondio: {url}")
                return datos
            except urllib.error.HTTPError as ex:
                fallos.append(f"{url} → HTTP {ex.code} {ex.reason}")
                break                      # un 403 o 404 no mejora reintentando
            except Exception as ex:
                if intento == 2:
                    fallos.append(f"{url} → {type(ex).__name__}: {ex}")
                else:
                    time.sleep(3)          # timeout o corte: vale un segundo intento
    raise RuntimeError("ninguna direccion respondio. Detalle:\n    " + "\n    ".join(fallos))

def stat(entrada, *nombres):
    """ESPN nombra las estadisticas distinto segun la liga: probamos varios."""
    for s in entrada.get("stats", []):
        for n in nombres:
            if s.get("name") == n or s.get("abbreviation") == n:
                v = s.get("value")
                if v is not None:
                    return int(v)
    return None

def extraer(cruda):
    """Devuelve {'A': [...], 'B': [...]} o revienta con un mensaje claro."""
    grupos = cruda.get("children") or []
    if len(grupos) != 2:
        raise RuntimeError(f"esperaba 2 zonas, ESPN devolvio {len(grupos)}")

    # Inventario de lo que ESPN manda para el primer equipo.
    # Sin esto es imposible saber si estamos leyendo la columna correcta.
    try:
        muestra = grupos[0]["standings"]["entries"][0]
        print("  campos que manda ESPN para", (muestra.get("team") or {}).get("displayName", "?"))
        for s in muestra.get("stats", []):
            print(f"    {s.get('name'):<22} {str(s.get('abbreviation')):<6} = {s.get('value')}")
        print("  temporada:", cruda.get("season") or cruda.get("seasonDisplay") or "no informada")
    except Exception:
        print("  (no se pudo listar los campos)")

    salida, desconocidos = {}, []
    for g in grupos:
        entradas = (g.get("standings") or {}).get("entries") or []
        equipos = []
        for e in entradas:
            nombre = (e.get("team") or {}).get("displayName", "")
            cid = a_id(nombre)
            if not cid:
                desconocidos.append(nombre)
                continue
            equipos.append({
                "id": cid,
                "nombre": CLUBES[cid][0],
                "espn": nombre,
                "pj":  stat(e, "gamesPlayed", "GP"),
                "pts": stat(e, "points", "P"),
                "gf":  stat(e, "pointsFor", "GF"),
                "gc":  stat(e, "pointsAgainst", "GA"),
            })
        # la zona la decide nuestra tabla, no el orden en que vengan los grupos
        zonas = {CLUBES[t["id"]][1] for t in equipos if t["id"] in CLUBES}
        if len(zonas) != 1:
            raise RuntimeError(f"un grupo de ESPN mezcla zonas nuestras: {zonas}")
        salida[zonas.pop()] = equipos

    if desconocidos:
        raise RuntimeError("nombres sin mapear (agregalos a ALIAS): " + ", ".join(sorted(set(desconocidos))))

    # dos equipos distintos no pueden apuntar al mismo club:
    # seria un alias mal escrito, y se perderia un equipo sin que nadie lo note
    vistos = {}
    for z, equipos in salida.items():
        for t in equipos:
            if t["id"] in vistos:
                raise RuntimeError(
                    f"dos equipos de ESPN apuntan al mismo club '{t['id']}': "
                    f"'{vistos[t['id']]}' y '{t['espn']}'. Hay un alias mal puesto.")
            vistos[t["id"]] = t["espn"]
    return salida

# ---------------------------------------------------------------- controles
def validar(zonas, previo):
    """Devuelve lista de problemas. Vacia = se puede publicar."""
    p = []
    if set(zonas) != {"A", "B"}:
        p.append(f"faltan zonas: {sorted(zonas)}")
        return p

    for z, equipos in zonas.items():
        if len(equipos) != 18:
            p.append(f"zona {z} tiene {len(equipos)} equipos, deberian ser 18")
        for t in equipos:
            for campo in ("pj", "pts", "gf", "gc"):
                if t[campo] is None:
                    p.append(f"{t['nombre']}: falta {campo}")
        for t in equipos:
            if t["pj"] is None or t["pts"] is None:
                continue
            if not (0 <= t["pj"] <= 36):
                p.append(f"{t['nombre']}: PJ fuera de rango ({t['pj']})")
            if t["pts"] > t["pj"] * 3:
                p.append(f"{t['nombre']}: {t['pts']} pts con {t['pj']} PJ, imposible")

    # --- controles de verosimilitud ---
    # Que un numero sea posible no significa que sea creible. Estos controles
    # existen porque una corrida devolvio a Acassuso puntero con 13 puntos.
    for z, equipos in zonas.items():
        pjs = [t["pj"] for t in equipos if t["pj"] is not None]
        ptss = [t["pts"] for t in equipos if t["pts"] is not None]
        if not pjs or not ptss:
            continue
        if max(pjs) - min(pjs) > 4:
            p.append(f"zona {z}: los PJ van de {min(pjs)} a {max(pjs)}, "
                     f"demasiada diferencia para una misma fecha")
        # un puntero promedia bastante mas de un punto por partido
        if max(pjs) >= 10 and max(ptss) < 1.2 * max(pjs):
            p.append(f"zona {z}: el puntero tiene {max(ptss)} pts en {max(pjs)} PJ. "
                     f"Muy poco para un lider: probablemente no estemos leyendo la "
                     f"columna de puntos, o sea otra temporada")

    # los puntos de un equipo nunca bajan: si bajaron, el parseo esta mal.
    # Se compara crudo contra crudo: una correccion manual no debe disparar la alarma.
    if previo:
        antes = previo.get("crudo") or {}
        for z, equipos in zonas.items():
            for t in equipos:
                vt = (antes.get(t["id"]) or {}).get("pts")
                if vt is not None and t["pts"] is not None and t["pts"] < vt:
                    p.append(f"{t['nombre']}: los puntos de ESPN bajaron de {vt} a {t['pts']}")
    return p


# ---------------------------------------------------------------- correcciones
def leer_correcciones():
    if not os.path.exists(CORRECCIONES):
        return [], []
    try:
        cru = json.load(open(CORRECCIONES, encoding="utf-8"))
    except Exception as ex:
        return [], [f"correcciones.json no es JSON valido: {ex}"]

    lista, errores = [], []
    for i, c in enumerate(cru.get("correcciones", []), 1):
        if not isinstance(c, dict):
            errores.append(f"correccion #{i}: tiene que ser un objeto")
            continue
        eq, campo, val = c.get("equipo"), c.get("campo"), c.get("valor")
        if eq not in CLUBES:
            errores.append(f"correccion #{i}: '{eq}' no es un id de club conocido")
        if campo not in CAMPOS:
            errores.append(f"correccion #{i}: campo '{campo}' invalido, usa {CAMPOS}")
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            errores.append(f"correccion #{i}: valor '{val}' tiene que ser un entero >= 0")
        if not c.get("fuente"):
            errores.append(f"correccion #{i}: falta la fuente (de donde sacaste el dato)")
        if not errores or all(f"#{i}:" not in e for e in errores):
            lista.append(c)
    return lista, errores


def aplicar_correcciones(zonas, correcciones):
    """Pisa valores de ESPN con los verificados a mano. Devuelve avisos."""
    porid = {t["id"]: t for z in zonas.values() for t in z}
    avisos = []
    for c in correcciones:
        t = porid.get(c["equipo"])
        if not t:
            avisos.append(f"{c['equipo']} no aparece en la tabla de ESPN, correccion ignorada")
            continue
        crudo = t[c["campo"]]
        if crudo == c["valor"]:
            avisos.append(f"YA NO HACE FALTA: {t['nombre']} {c['campo']}={c['valor']}, "
                          f"ESPN se puso al dia. Borrala de correcciones.json")
            continue
        t[c["campo"]] = c["valor"]
        t.setdefault("verificado", []).append(c["campo"])
        t.setdefault("notas", []).append(
            f"{c['campo']}: ESPN decia {crudo}, corregido a {c['valor']} "
            f"(fuente: {c['fuente']})")
        avisos.append(f"aplicada: {t['nombre']} {c['campo']} {crudo} -> {c['valor']} "
                      f"[{c['fuente']}]")
    return avisos

def ordenar_zona(equipos):
    return sorted(equipos, key=lambda t: (-t["pts"], -(t["gf"] - t["gc"]), -t["gf"], t["nombre"]))

# ---------------------------------------------------------------- main
def main():
    previo = None
    if os.path.exists(DATA):
        try:
            previo = json.load(open(DATA, encoding="utf-8"))
        except Exception:
            previo = None

    ahora = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    try:
        zonas = extraer(bajar())
    except Exception as ex:
        json.dump({"estado": "error", "detalle": str(ex), "intento": ahora,
                   "ultimo_ok": (previo or {}).get("actualizado")},
                  open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("FALLO, no se toca data.json:", ex)
        return 1

    problemas = validar(zonas, previo)
    correcciones, errores_corr = leer_correcciones()
    problemas += errores_corr

    if problemas:
        json.dump({"estado": "error", "detalle": problemas, "intento": ahora,
                   "ultimo_ok": (previo or {}).get("actualizado")},
                  open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("VALIDACION FALLIDA, no se toca data.json:")
        for x in problemas:
            print("  -", x)
        return 1

    # foto de lo que dijo ESPN, antes de tocar nada: sirve para el control de la proxima corrida
    crudo = {t["id"]: {c: t[c] for c in CAMPOS} for z in zonas.values() for t in z}

    avisos = aplicar_correcciones(zonas, correcciones)
    for a in avisos:
        print("  ·", a)

    for z in zonas:
        zonas[z] = ordenar_zona(zonas[z])
        for i, t in enumerate(zonas[z], 1):
            t["pos"] = i
            t["dif"] = t["gf"] - t["gc"]

    verificados = sum(len(t.get("verificado", []))
                      for z in zonas.values() for t in z)

    json.dump({"actualizado": ahora, "fuente": "ESPN arg.2",
               "verificados": verificados, "zonas": zonas, "crudo": crudo},
              open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"estado": "ok", "intento": ahora, "ultimo_ok": ahora,
               "correcciones_aplicadas": avisos},
              open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("OK ·", ahora, f"· {verificados} valores verificados a mano")
    for z in ("A", "B"):
        print(f"  Zona {z}: " + " | ".join(
            f"{t['pos']}.{t['nombre']} {t['pts']}pts/{t['pj']}PJ" for t in zonas[z][:4]))
    return 0

if __name__ == "__main__":
    sys.exit(main())
