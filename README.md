# Llave del Reducido — Primera Nacional 2026

Simulador de la llave que se actualiza solo con la tabla de posiciones.

## Cómo está armado

```
index.html                        la página (no tiene datos adentro)
data.json                         la tabla, la escribe el scraper
correcciones.json                 tus correcciones a mano sobre lo que trae ESPN
estado.json                       si la última corrida salió bien o mal
scraper/actualizar.py             baja ESPN arg.2, valida y escribe data.json
.github/workflows/actualizar.yml  lo corre cada 3 horas
```

La página no tiene ni un dato quemado. Lee `data.json`, ordena las dos zonas,
y **deriva los siete cruces de primera fase** aplicando el reglamento:
2-8, 3-7 y 4-6 cruzados entre zonas, más 5 contra 5. La localía la define el
mejor ubicado, y entre los dos quintos desempata por puntos, diferencia de gol
y goles a favor.

## Puesta en marcha

1. Repo nuevo en GitHub, **público** (Pages gratis necesita que lo sea).
2. Subí estos archivos respetando las carpetas.
3. Settings → Pages → Source: `Deploy from a branch`, rama `main`, carpeta `/root`.
4. Settings → Actions → General → Workflow permissions: **Read and write**.
   Sin esto el bot no puede escribir `data.json`.
5. Pestaña Actions → `Actualizar tabla` → `Run workflow`. Esa primera corrida
   es la que crea `data.json`.
6. Tu URL queda en `https://TUUSUARIO.github.io/NOMBREDELREPO/`.

**Antes de la primera corrida la página no muestra nada**, porque `data.json`
todavía no existe. Es a propósito: preferí eso a dejar una tabla escrita a mano
que después nadie sepa si está vigente.

## La regla que hace que esto sea confiable

Si algo no cierra, el scraper **no pisa** `data.json`. Corta y deja la tabla
anterior con su fecha a la vista. Los controles que corre:

- ESPN tiene que devolver exactamente 2 zonas, de 18 equipos cada una.
- Todos los nombres tienen que estar en la tabla de alias. Uno solo sin mapear y corta.
- PJ entre 0 y 36, y puntos nunca mayores a PJ × 3.
- **Los puntos de un equipo nunca pueden bajar** respecto de la corrida anterior.
  Es el control más útil: si el parseo se rompe y empieza a leer otra columna,
  esto lo caza enseguida.

Cuando falla, `estado.json` guarda el motivo y en Actions queda una advertencia.
La página avisa en rojo si la tabla tiene más de 30 horas.

## Cuando ESPN se equivoca: correcciones manuales

ESPN es la fuente automática, pero no es la que vos validás. Para eso está
`correcciones.json`: escribís ahí el valor que verificaste en Promiedos y el
pipeline lo aplica encima del dato automático.

```json
{
  "correcciones": [
    { "equipo": "colon", "campo": "pts", "valor": 45,
      "fuente": "Promiedos", "fecha": "2026-08-25",
      "motivo": "ESPN no cargó el partido vs Ferro" }
  ]
}
```

- `campo` puede ser `pts`, `pj`, `gf` o `gc`.
- `equipo` es el id interno, está en la tabla `CLUBES` del scraper.
- `fuente` es obligatoria. Si no ponés de dónde sacaste el dato, el script corta.

El valor corregido aparece en la página con un tilde dorado al lado del nombre,
y arriba se cuenta cuántos valores están verificados a mano. Pasando el mouse por
el tilde se ve qué decía ESPN y de dónde salió la corrección.

**Se limpian solas.** Cuando ESPN se pone al día y su valor coincide con tu
corrección, el script no la aplica y te avisa en el log que ya podés borrarla.

**No ensucian el control de puntos.** El archivo guarda aparte una foto de lo que
dijo ESPN (`crudo`), y el control de "los puntos nunca bajan" compara crudo contra
crudo. Así una corrección hacia arriba no dispara una falsa alarma en la corrida
siguiente, pero una caída real la sigue detectando.



ESPN no documenta este endpoint ni se compromete a mantenerlo. Puede cambiar el
formato o el nombre de un club sin aviso. Cuando pase, el scraper corta y te
avisa; el arreglo suele ser agregar un alias en `scraper/actualizar.py`.

También conviene no abusar: una consulta cada 3 horas es razonable, cada 5
minutos no.

## Cuando empiece el Reducido

Esto hoy mantiene al día **la tabla**, que es lo que define quiénes clasifican
y contra quién. Los resultados de las llaves, del 31 de octubre en adelante, hoy
los pone el usuario a mano haciendo clic. Automatizar eso es otro paso: hay que
leer el fixture de playoffs, que ESPN publica con otra estructura.
