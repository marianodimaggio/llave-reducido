#!/usr/bin/env python3
"""
Genera fuerzas.json, el modelo de probabilidades que consume la app.

QUE MODELO ES
Poisson bivariado tipo Dixon-Coles, el estandar del rubro desde 1997:
ataque y defensa por equipo separando local de visitante, nivel general de
goles y ventaja de local estimados de los datos, correccion rho para los
resultados 0-0, 1-0, 0-1 y 1-1 que el Poisson independiente subestima, y
regularizacion sobre los parametros de equipo.

POR QUE NO USA xG
Se probaron cuatro mezclas de goles y xG con validacion fuera de muestra y
gano la que usa solo goles. Va contra la literatura general, pero el xG de
FootyStats en esta categoria viene inflado un 35% y hay equipos con desvios
grandes y persistentes. Medido sobre una sola temporada: alcanza para decir
"aca no ayuda", no para descartar el xG en general.

SOBRE EL ENCOGIMIENTO
La regularizacion (ridge=20) ya encoge las fuerzas durante el ajuste. Se probo
encogerlas mas todavia y empeora: la validacion da 1,0263 con las fuerzas
completas y 1,0313 encogiendolas a un cuarto. Asi que se usan completas.

LO QUE LA VALIDACION DICE, Y HAY QUE DECIRLO
Sobre 267 partidos que el modelo no vio:
  modelo Dixon-Coles      logloss 1,0263
  no usar datos de equipos logloss 1,0244
  casas de apuestas        logloss 1,0138
El modelo no le gana a no saber nada, y el mercado le gana a los dos por poco.
Esta categoria es, partido a partido, casi impredecible: 32% de empates y 1,94
goles por partido. Lo que si esta bien medido es la ventaja de local (x1,60 en
goles) y la estructura del torneo, que es lo que domina el reparto de ascensos.

Uso:  python3 generar_fuerzas.py partidos.csv
"""
import json, sys, os, datetime
import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, 'scraper'))
import actualizar as A
from modelo_dc import leer, preparar, ajustar, matriz, logloss, rps, resultado, del_mercado

N_SIM   = 10000
RIDGE   = 20.0     # elegidos por validacion fuera de muestra
DECAY   = 0.0
ENCOGER = 1.00   # sin encogimiento extra: la validacion mostro que empeora
SALIDA  = os.path.join(AQUI, 'fuerzas.json')


def tabla(j):
    t = {}
    for _, r in j.iterrows():
        for yo, gy, gr in [(r['ih'], r['home_team_goal_count'], r['away_team_goal_count']),
                           (r['ia'], r['away_team_goal_count'], r['home_team_goal_count'])]:
            e = t.setdefault(yo, {'pj': 0, 'pts': 0, 'gf': 0, 'gc': 0})
            e['pj'] += 1; e['gf'] += gy; e['gc'] += gr
            e['pts'] += 3 if gy > gr else (1 if gy == gr else 0)
    for k, v in t.items():
        v['dif'] = v['gf'] - v['gc']; v['z'] = A.CLUBES[k][1]; v['n'] = A.CLUBES[k][0]
    for z in ('A', 'B'):
        eq = sorted([k for k in t if t[k]['z'] == z],
                    key=lambda k: (-t[k]['pts'], -t[k]['dif'], -t[k]['gf']))
        for i, k in enumerate(eq, 1):
            t[k]['pos'] = i
    return t


def lam(mod, h, a, s=ENCOGER):
    l = np.exp(mod['mu'] + mod['casa'] + s * (mod['atk'][h] - mod['dfn'][a]))
    m = np.exp(mod['mu'] + s * (mod['atk'][a] - mod['dfn'][h]))
    return float(np.clip(l, .05, 8)), float(np.clip(m, .05, 8))


def p1x2(mod, h, a, s=ENCOGER):
    M = matriz(*lam(mod, h, a, s), mod['rho'])
    return np.tril(M, -1).sum(), np.trace(M), np.triu(M, 1).sum()


def validar(j, equipos, desde=0.45, cada=25):
    """Predice solo partidos que el modelo no vio y compara con dos referencias."""
    ini = int(len(j) * desde)
    ps_m, ps_b, ps_k, res = [], [], [], []
    mod = None
    for i in range(ini, len(j)):
        if mod is None or (i - ini) % cada == 0:
            mod = ajustar(j.iloc[:i], equipos, mezcla=0.0, xi=DECAY, ridge=RIDGE)
        r = j.iloc[i]; tr = j.iloc[:i]
        b = np.array([(tr['home_team_goal_count'] > tr['away_team_goal_count']).mean(),
                      (tr['home_team_goal_count'] == tr['away_team_goal_count']).mean(),
                      (tr['home_team_goal_count'] < tr['away_team_goal_count']).mean()])
        ps_m.append(p1x2(mod, r['ih'], r['ia'])); ps_b.append(b / b.sum())
        ps_k.append(del_mercado(r)); res.append(resultado(r))

    idx = [i for i, p in enumerate(ps_k) if p is not None]
    sub = lambda L: [L[i] for i in idx]
    rk = [res[i] for i in idx]
    return {
        'partidos_evaluados': len(res),
        'modelo':    {'logloss': round(logloss(ps_m, res), 4), 'rps': round(rps(ps_m, res), 4)},
        'sin_datos': {'logloss': round(logloss(ps_b, res), 4), 'rps': round(rps(ps_b, res), 4)},
        'mercado':   {'logloss': round(logloss(sub(ps_k), rk), 4),
                      'rps': round(rps(sub(ps_k), rk), 4), 'n': len(idx)},
    }


def simular(t, mod, pen, n=N_SIM):
    rng = np.random.default_rng(7)
    ids = sorted(t); idx = {x: i for i, x in enumerate(ids)}
    zona = np.array([t[x]['z'] for x in ids])

    lamL = np.array([lam(mod, r['ih'], r['ia'])[0] for _, r in pen.iterrows()])
    lamV = np.array([lam(mod, r['ih'], r['ia'])[1] for _, r in pen.iterrows()])
    ph = np.array([idx[r['ih']] for _, r in pen.iterrows()])
    pa = np.array([idx[r['ia']] for _, r in pen.iterrows()])

    PTS = np.tile(np.array([t[x]['pts'] for x in ids], float), (n, 1))
    DIF = np.tile(np.array([t[x]['dif'] for x in ids], float), (n, 1))
    GF  = np.tile(np.array([t[x]['gf']  for x in ids], float), (n, 1))
    gl = rng.poisson(lamL, size=(n, len(pen))); gv = rng.poisson(lamV, size=(n, len(pen)))
    pl = np.where(gl > gv, 3, np.where(gl == gv, 1, 0))
    pv = np.where(gv > gl, 3, np.where(gl == gv, 1, 0))
    for m in range(len(pen)):
        PTS[:, ph[m]] += pl[:, m]; PTS[:, pa[m]] += pv[:, m]
        DIF[:, ph[m]] += gl[:, m] - gv[:, m]; DIF[:, pa[m]] += gv[:, m] - gl[:, m]
        GF[:, ph[m]] += gl[:, m]; GF[:, pa[m]] += gv[:, m]

    def part(a, b, neutral=False):
        if neutral:
            base = np.exp(mod['mu'] + mod['casa'] / 2)     # cancha neutral: mitad de ventaja
            la = base * np.exp(ENCOGER * (mod['atk'][a] - mod['dfn'][b]))
            lb = base * np.exp(ENCOGER * (mod['atk'][b] - mod['dfn'][a]))
        else:
            la, lb = lam(mod, a, b)
        return rng.poisson(max(la, .05)), rng.poisson(max(lb, .05))

    def unico(m_, p_, neutral=False):
        ga, gb = part(m_, p_, neutral)
        if neutral:
            if ga != gb: return m_ if ga > gb else p_
            return m_ if rng.random() < .5 else p_
        return m_ if ga >= gb else p_          # ventaja deportiva

    def serie(m_, p_, penales=False):
        ip, im = part(p_, m_); vm, vp = part(m_, p_)
        pm = (3 if vm > vp else 1 if vm == vp else 0) + (3 if im > ip else 1 if im == ip else 0)
        pp = (3 if vp > vm else 1 if vm == vp else 0) + (3 if ip > im else 1 if im == ip else 0)
        if pm != pp: return m_ if pm > pp else p_
        d = (im + vm) - (ip + vp)
        if d != 0: return m_ if d > 0 else p_
        if penales: return m_ if rng.random() < .5 else p_
        return m_

    pri = np.zeros(len(ids), int); seg = np.zeros(len(ids), int)
    red = np.zeros(len(ids), int); t4 = np.zeros(len(ids), int)

    for s in range(n):
        orden, posic = {}, {}
        for z in ('A', 'B'):
            mm = np.where(zona == z)[0]
            cl = sorted(mm, key=lambda i: (-PTS[s, i], -DIF[s, i], -GF[s, i]))
            orden[z] = [ids[i] for i in cl]
            for k2, i in enumerate(cl, 1):
                posic[ids[i]] = k2
                if k2 <= 4: t4[i] += 1
                if 2 <= k2 <= 8: red[i] += 1
        pA, pB = orden['A'][0], orden['B'][0]
        camp = unico(pA, pB, neutral=True); perd = pB if camp == pA else pA
        pri[idx[camp]] += 1

        def mejor(x, y):
            if posic[x] != posic[y]: return x if posic[x] < posic[y] else y
            for M in (PTS, DIF, GF):
                if M[s, idx[x]] != M[s, idx[y]]: return x if M[s, idx[x]] > M[s, idx[y]] else y
            return x

        cruces = []
        for alto, bajo in ((2, 8), (3, 7), (4, 6)):
            cruces.append((orden['A'][alto - 1], orden['B'][bajo - 1]))
            cruces.append((orden['B'][alto - 1], orden['A'][bajo - 1]))
        cruces.append((orden['A'][4], orden['B'][4]))

        vivos = [perd]
        for x, y in cruces:
            m_ = mejor(x, y); vivos.append(unico(m_, y if m_ == x else x))
        sem = lambda L: sorted(L, key=lambda x: (posic[x], -PTS[s, idx[x]],
                                                 -DIF[s, idx[x]], -GF[s, idx[x]]))
        o8 = sem(vivos)
        o4 = sem([serie(o8[a], o8[b]) for a, b in ((0, 7), (1, 6), (2, 5), (3, 4))])
        o2 = sem([serie(o4[a], o4[b]) for a, b in ((0, 3), (1, 2))])
        seg[idx[serie(o2[0], o2[1], penales=True)]] += 1

    return {ids[i]: {'primero': round(pri[i] / n * 100, 1),
                     'segundo': round(seg[i] / n * 100, 1),
                     'asciende': round((pri[i] + seg[i]) / n * 100, 1),
                     'reducido': round(red[i] / n * 100, 1),
                     'top4': round(t4[i] / n * 100, 1)} for i in range(len(ids))}


def main():
    csv = sys.argv[1] if len(sys.argv) > 1 else None
    if not csv or not os.path.exists(csv):
        raise SystemExit('uso: python3 generar_fuerzas.py partidos.csv')

    d = leer(csv)
    jug = d[d['status'] == 'complete'].reset_index(drop=True)
    jug, k = preparar(jug)
    pen = d[d['status'] != 'complete']
    t = tabla(jug)
    if len(t) != 36:
        raise SystemExit(f'la tabla tiene {len(t)} equipos, deberian ser 36')
    equipos = sorted(t)

    print(f'jugados {len(jug)} · pendientes {len(pen)}')
    print('validando fuera de muestra...')
    val = validar(jug, equipos)
    for cual in ('modelo', 'sin_datos', 'mercado'):
        v = val[cual]
        print(f"  {cual:11} logloss {v['logloss']}  rps {v['rps']}")

    print('ajustando el modelo final...')
    mod = ajustar(jug, equipos, mezcla=0.0, xi=DECAY, ridge=RIDGE)
    base = np.array([(jug['home_team_goal_count'] > jug['away_team_goal_count']).mean(),
                     (jug['home_team_goal_count'] == jug['away_team_goal_count']).mean(),
                     (jug['home_team_goal_count'] < jug['away_team_goal_count']).mean()])
    base = base / base.sum()
    print(f"  ventaja de local: x{np.exp(mod['casa']):.2f} en goles · rho {mod['rho']:.4f}")

    print(f'simulando {N_SIM} veces...')
    sim = simular(t, mod, pen)

    json.dump({
        'generado': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'datos_hasta': jug['f'].max().strftime('%Y-%m-%d'),
        'partidos_usados': int(len(jug)),
        'pendientes': int(len(pen)),
        'simulaciones': N_SIM,
        'ventaja_local': round(float(np.exp(mod['casa'])), 3),
        'rho': round(mod['rho'], 4),
        'recalibracion_xg': round(float(k), 4),
        'base_liga': {'local': round(float(base[0]), 4), 'empate': round(float(base[1]), 4),
                      'visita': round(float(base[2]), 4)},
        'validacion': val,
        'parametros': {'mu': round(mod['mu'], 5), 'casa': round(mod['casa'], 5),
                       'rho': round(mod['rho'], 5), 'encoger': ENCOGER},
        'fuerzas': {x: {'atk': round(mod['atk'][x], 4), 'dfn': round(mod['dfn'][x], 4)}
                    for x in equipos},
        'ascensos': sim,
    }, open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print(f'escrito {SALIDA} ({os.path.getsize(SALIDA)/1024:.1f} KB)')
    for x in sorted(sim, key=lambda x: -sim[x]['asciende'])[:6]:
        print(f"  {t[x]['n']:20} asciende {sim[x]['asciende']:5.1f}%")


if __name__ == '__main__':
    main()
