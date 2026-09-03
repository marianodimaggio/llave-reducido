#!/usr/bin/env python3
"""
Genera fuerzas.json a partir del CSV de partidos de FootyStats.

Ese archivo es lo unico que la app necesita para mostrar probabilidades.
Contiene:
  - la fuerza de ataque y defensa de cada equipo, en xG recalibrado
  - los promedios de la liga para local y visitante
  - el reparto de ascensos, precalculado con 10.000 simulaciones

Se regenera cada vez que se actualiza el CSV. Si el archivo no existe,
la app funciona igual, solo sin la capa de probabilidades.

Uso:  python3 generar_fuerzas.py archivo.csv
"""
import json, sys, os, datetime
import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, 'scraper'))
import actualizar as A

N_SIM = 10000
SALIDA = os.path.join(AQUI, 'fuerzas.json')


def cargar(csv):
    d = pd.read_csv(csv)
    d['ih'] = d['home_team_name'].map(A.a_id)
    d['ia'] = d['away_team_name'].map(A.a_id)
    sin = sorted(set(d[d['ih'].isna()]['home_team_name']) |
                 set(d[d['ia'].isna()]['away_team_name']))
    if sin:
        raise SystemExit('nombres sin mapear en el CSV: ' + ', '.join(sin))
    return d


def tabla(j):
    t = {}
    for _, r in j.iterrows():
        for yo, gy, gr in [(r['ih'], r['home_team_goal_count'], r['away_team_goal_count']),
                           (r['ia'], r['away_team_goal_count'], r['home_team_goal_count'])]:
            e = t.setdefault(yo, {'pj': 0, 'pts': 0, 'gf': 0, 'gc': 0})
            e['pj'] += 1; e['gf'] += gy; e['gc'] += gr
            e['pts'] += 3 if gy > gr else (1 if gy == gr else 0)
    for k, v in t.items():
        v['dif'] = v['gf'] - v['gc']
        v['z'] = A.CLUBES[k][1]
        v['n'] = A.CLUBES[k][0]
    for z in ('A', 'B'):
        eq = sorted([k for k in t if t[k]['z'] == z],
                    key=lambda k: (-t[k]['pts'], -t[k]['dif'], -t[k]['gf']))
        for i, k in enumerate(eq, 1):
            t[k]['pos'] = i
    return t


def fuerzas(j):
    """Ataque y defensa por equipo. El xG se recalibra a los goles reales."""
    c = j.dropna(subset=['team_a_xg', 'team_b_xg'])
    c = c[(c['team_a_xg'] > 0) | (c['team_b_xg'] > 0)]

    goles = c['home_team_goal_count'].sum() + c['away_team_goal_count'].sum()
    xg = c['team_a_xg'].sum() + c['team_b_xg'].sum()
    k = float(goles / xg)

    mL = float(c['team_a_xg'].mean() * k)
    mV = float(c['team_b_xg'].mean() * k)

    ac = {}
    for _, r in c.iterrows():
        for yo, f, ct, loc in [(r['ih'], r['team_a_xg'], r['team_b_xg'], True),
                               (r['ia'], r['team_b_xg'], r['team_a_xg'], False)]:
            e = ac.setdefault(yo, {'fL': 0, 'cL': 0, 'nL': 0, 'fV': 0, 'cV': 0, 'nV': 0})
            if loc: e['fL'] += f * k; e['cL'] += ct * k; e['nL'] += 1
            else:   e['fV'] += f * k; e['cV'] += ct * k; e['nV'] += 1

    F = {}
    for id_, e in ac.items():
        F[id_] = {
            'atkL': round((e['fL'] / e['nL']) / mL, 4) if e['nL'] else 1.0,
            'defL': round((e['cL'] / e['nL']) / mV, 4) if e['nL'] else 1.0,
            'atkV': round((e['fV'] / e['nV']) / mV, 4) if e['nV'] else 1.0,
            'defV': round((e['cV'] / e['nV']) / mL, 4) if e['nV'] else 1.0,
        }
    return F, mL, mV, k, len(c)


def simular(t, F, mL, mV, pendientes, n=N_SIM):
    """Sortea lo que falta del torneo y despues los playoffs, n veces."""
    rng = np.random.default_rng(7)
    ids = sorted(t)
    idx = {x: i for i, x in enumerate(ids)}
    zona = np.array([t[x]['z'] for x in ids])

    esp = lambda a, b: (max(mL * F[a]['atkL'] * F[b]['defV'], .15),
                        max(mV * F[b]['atkV'] * F[a]['defL'], .15))

    lamL = np.array([esp(r['ih'], r['ia'])[0] for _, r in pendientes.iterrows()])
    lamV = np.array([esp(r['ih'], r['ia'])[1] for _, r in pendientes.iterrows()])
    ph = np.array([idx[r['ih']] for _, r in pendientes.iterrows()])
    pa = np.array([idx[r['ia']] for _, r in pendientes.iterrows()])

    PTS = np.tile(np.array([t[x]['pts'] for x in ids], float), (n, 1))
    DIF = np.tile(np.array([t[x]['dif'] for x in ids], float), (n, 1))
    GF  = np.tile(np.array([t[x]['gf']  for x in ids], float), (n, 1))

    gl = rng.poisson(lamL, size=(n, len(pendientes)))
    gv = rng.poisson(lamV, size=(n, len(pendientes)))
    pl = np.where(gl > gv, 3, np.where(gl == gv, 1, 0))
    pv = np.where(gv > gl, 3, np.where(gl == gv, 1, 0))
    for m in range(len(pendientes)):
        PTS[:, ph[m]] += pl[:, m]; PTS[:, pa[m]] += pv[:, m]
        DIF[:, ph[m]] += gl[:, m] - gv[:, m]; DIF[:, pa[m]] += gv[:, m] - gl[:, m]
        GF[:, ph[m]] += gl[:, m]; GF[:, pa[m]] += gv[:, m]

    def sortear(a, b, neutral=False):
        if neutral:
            base = np.sqrt(mL * mV)
            la = base * (F[a]['atkL'] + F[a]['atkV']) / 2 * (F[b]['defL'] + F[b]['defV']) / 2
            lb = base * (F[b]['atkL'] + F[b]['atkV']) / 2 * (F[a]['defL'] + F[a]['defV']) / 2
        else:
            la, lb = esp(a, b)
        return rng.poisson(max(la, .15)), rng.poisson(max(lb, .15))

    def unico(m_, p_, neutral=False):
        ga, gb = sortear(m_, p_, neutral)
        if neutral:
            if ga != gb: return m_ if ga > gb else p_
            return m_ if rng.random() < .5 else p_
        return m_ if ga >= gb else p_

    def serie(m_, p_, penales=False):
        ip, im = sortear(p_, m_)
        vm, vp = sortear(m_, p_)
        pm = (3 if vm > vp else 1 if vm == vp else 0) + (3 if im > ip else 1 if im == ip else 0)
        pp = (3 if vp > vm else 1 if vm == vp else 0) + (3 if ip > im else 1 if im == ip else 0)
        if pm != pp: return m_ if pm > pp else p_
        d = (im + vm) - (ip + vp)
        if d != 0: return m_ if d > 0 else p_
        if penales: return m_ if rng.random() < .5 else p_
        return m_

    primero = np.zeros(len(ids), int)
    segundo = np.zeros(len(ids), int)
    reducido = np.zeros(len(ids), int)
    top4 = np.zeros(len(ids), int)

    for s in range(n):
        orden, posic = {}, {}
        for z in ('A', 'B'):
            m = np.where(zona == z)[0]
            cl = sorted(m, key=lambda i: (-PTS[s, i], -DIF[s, i], -GF[s, i]))
            orden[z] = [ids[i] for i in cl]
            for k2, i in enumerate(cl, 1):
                posic[ids[i]] = k2
                if k2 <= 4: top4[i] += 1
                if 2 <= k2 <= 8: reducido[i] += 1

        pA, pB = orden['A'][0], orden['B'][0]
        camp = unico(pA, pB, neutral=True)
        perd = pB if camp == pA else pA
        primero[idx[camp]] += 1

        def mejor(x, y):
            if posic[x] != posic[y]: return x if posic[x] < posic[y] else y
            i, jj = idx[x], idx[y]
            for M in (PTS, DIF, GF):
                if M[s, i] != M[s, jj]: return x if M[s, i] > M[s, jj] else y
            return x

        cruces = []
        for alto, bajo in ((2, 8), (3, 7), (4, 6)):
            cruces.append((orden['A'][alto - 1], orden['B'][bajo - 1]))
            cruces.append((orden['B'][alto - 1], orden['A'][bajo - 1]))
        cruces.append((orden['A'][4], orden['B'][4]))

        vivos = [perd]
        for x, y in cruces:
            m_ = mejor(x, y)
            vivos.append(unico(m_, y if m_ == x else x))

        sembrar = lambda L: sorted(L, key=lambda x: (posic[x], -PTS[s, idx[x]],
                                                     -DIF[s, idx[x]], -GF[s, idx[x]]))
        o8 = sembrar(vivos)
        o4 = sembrar([serie(o8[a], o8[b]) for a, b in ((0, 7), (1, 6), (2, 5), (3, 4))])
        o2 = sembrar([serie(o4[a], o4[b]) for a, b in ((0, 3), (1, 2))])
        segundo[idx[serie(o2[0], o2[1], penales=True)]] += 1

    return {ids[i]: {
        'primero': round(primero[i] / n * 100, 1),
        'segundo': round(segundo[i] / n * 100, 1),
        'asciende': round((primero[i] + segundo[i]) / n * 100, 1),
        'reducido': round(reducido[i] / n * 100, 1),
        'top4': round(top4[i] / n * 100, 1),
    } for i in range(len(ids))}


def main():
    csv = sys.argv[1] if len(sys.argv) > 1 else None
    if not csv or not os.path.exists(csv):
        raise SystemExit('uso: python3 generar_fuerzas.py archivo.csv')

    d = cargar(csv)
    jug = d[d['status'] == 'complete']
    pen = d[d['status'] != 'complete']
    t = tabla(jug)
    F, mL, mV, k, con_xg = fuerzas(jug)

    if len(t) != 36:
        raise SystemExit(f'la tabla tiene {len(t)} equipos, deberian ser 36')

    print(f'jugados {len(jug)} · pendientes {len(pen)} · con xG {con_xg}')
    print(f'recalibracion del xG: x{k:.3f}  (sobreestima un {(1/k-1)*100:.1f}%)')
    print(f'simulando {N_SIM} veces...')
    sim = simular(t, F, mL, mV, pen)

    ultima = pd.to_datetime(jug['date_GMT'], format='%b %d %Y - %I:%M%p',
                            errors='coerce').max()
    salida = {
        'generado': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'datos_hasta': ultima.strftime('%Y-%m-%d') if pd.notna(ultima) else None,
        'partidos_usados': int(con_xg),
        'pendientes': int(len(pen)),
        'simulaciones': N_SIM,
        'recalibracion_xg': round(k, 4),
        'media_local': round(mL, 4),
        'media_visita': round(mV, 4),
        'fuerzas': F,
        'ascensos': sim,
    }
    json.dump(salida, open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'escrito {SALIDA}  ({os.path.getsize(SALIDA)/1024:.1f} KB)')
    for x in sorted(sim, key=lambda x: -sim[x]['asciende'])[:6]:
        print(f"  {t[x]['n']:20} asciende {sim[x]['asciende']:5.1f}%")


if __name__ == '__main__':
    main()
