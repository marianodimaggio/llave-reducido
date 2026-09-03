#!/usr/bin/env python3
"""
Modelo de probabilidades tipo Dixon-Coles, validado fuera de muestra.

Que incluye, y de donde sale cada decision:

- Poisson bivariado con ataque y defensa por equipo mas ventaja de local.
  Es la base de casi todos los modelos de futbol desde 1997.
- Correccion rho de Dixon-Coles para los resultados 0-0, 1-0, 0-1 y 1-1,
  que el Poisson independiente subestima. En ligas de pocos goles y muchos
  empates, como esta, importa.
- Decaimiento temporal exponencial: los partidos viejos pesan menos.
- Regularizacion (ridge) sobre los parametros de equipo. Con 36 equipos y
  27 fechas hay 72 parametros para pocos datos: sin encoger, el modelo
  memoriza ruido.
- Senal mezclada entre goles y xG recalibrado. El xG predice mejor que los
  goles, pero mezclarlos suele ganarle a cualquiera de los dos solo.

Todo lo que es una decision libre (rho, decaimiento, encogimiento, mezcla)
se elige por validacion fuera de muestra, no a ojo.

Se compara contra tres referencias:
  1. los porcentajes base de la liga, sin datos de equipos
  2. las cuotas de las casas de apuestas, que es el techo realista
  3. el modelo simple que ya teniamos
"""
import numpy as np, pandas as pd, sys, os, itertools
from math import lgamma
from scipy.optimize import minimize
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scraper'))
import actualizar as A

TOPE = 9   # goles maximos considerados en la matriz de resultados


# ---------------------------------------------------------------- datos
def leer(csv):
    d = pd.read_csv(csv)
    d['ih'] = d['home_team_name'].map(A.a_id)
    d['ia'] = d['away_team_name'].map(A.a_id)
    d['f'] = pd.to_datetime(d['date_GMT'], format='%b %d %Y - %I:%M%p', errors='coerce')
    d = d.dropna(subset=['ih', 'ia', 'f'])
    return d.sort_values('f').reset_index(drop=True)


def preparar(j):
    """Agrega la senal mezclada de goles y xG recalibrado."""
    gl = j['home_team_goal_count'].sum() + j['away_team_goal_count'].sum()
    xg = j['team_a_xg'].fillna(0).sum() + j['team_b_xg'].fillna(0).sum()
    k = gl / xg if xg > 0 else 1.0
    j = j.copy()
    j['xgL'] = j['team_a_xg'].fillna(j['home_team_goal_count']) * k
    j['xgV'] = j['team_b_xg'].fillna(j['away_team_goal_count']) * k
    return j, k


# ---------------------------------------------------------------- Dixon-Coles
def tau(x, y, l, m, rho):
    """Correccion de los cuatro resultados bajos."""
    if x == 0 and y == 0: return 1 - l * m * rho
    if x == 0 and y == 1: return 1 + l * rho
    if x == 1 and y == 0: return 1 + m * rho
    if x == 1 and y == 1: return 1 - rho
    return 1.0


def matriz(l, m, rho):
    """Distribucion conjunta de resultados, ya corregida."""
    pl = np.exp(-l) * l ** np.arange(TOPE) / np.array([np.exp(lgamma(i + 1)) for i in range(TOPE)])
    pm = np.exp(-m) * m ** np.arange(TOPE) / np.array([np.exp(lgamma(i + 1)) for i in range(TOPE)])
    M = np.outer(pl, pm)
    for x in range(2):
        for y in range(2):
            M[x, y] *= tau(x, y, l, m, rho)
    return M / M.sum()


def a_1x2(M):
    return np.tril(M, -1).sum(), np.trace(M), np.triu(M, 1).sum()


# ---------------------------------------------------------------- ajuste
def ajustar(tr, equipos, mezcla, xi, ridge, rho_fijo=None):
    """
    Estima ataque y defensa por equipo maximizando la verosimilitud pesada.
    mezcla: 1 = solo xG, 0 = solo goles.
    xi: decaimiento por dia. ridge: fuerza del encogimiento.
    """
    n = len(equipos)
    ind = {e: i for i, e in enumerate(equipos)}
    ult = tr['f'].max()
    w = np.exp(-xi * (ult - tr['f']).dt.days.values)

    # la senal sobre la que se ajusta
    sL = mezcla * tr['xgL'].values + (1 - mezcla) * tr['home_team_goal_count'].values
    sV = mezcla * tr['xgV'].values + (1 - mezcla) * tr['away_team_goal_count'].values
    ih = np.array([ind[x] for x in tr['ih']])
    ia = np.array([ind[x] for x in tr['ia']])
    gh = tr['home_team_goal_count'].values.astype(int)
    ga = tr['away_team_goal_count'].values.astype(int)

    def desarmar(p):
        atk = np.concatenate([[0.0], p[:n - 1]])
        dfn = np.concatenate([[0.0], p[n - 1:2 * n - 2]])
        atk = atk - atk.mean(); dfn = dfn - dfn.mean()     # identificabilidad
        mu   = p[2 * n - 2]                                # nivel general de goles
        casa = p[2 * n - 1]                                # ventaja de local
        rho  = rho_fijo if rho_fijo is not None else p[2 * n]
        return atk, dfn, mu, casa, rho

    def neg(p):
        atk, dfn, mu, casa, rho = desarmar(p)
        l = np.exp(mu + casa + atk[ih] - dfn[ia])
        m = np.exp(mu + atk[ia] - dfn[ih])
        l = np.clip(l, .05, 8); m = np.clip(m, .05, 8)
        # verosimilitud Poisson sobre la senal (cuasi-verosimilitud si es xG)
        ll = w * (sL * np.log(l) - l + sV * np.log(m) - m)
        # correccion de resultados bajos, sobre los goles reales
        if abs(rho) > 1e-6:
            corr = np.ones(len(l))
            bajo = (gh <= 1) & (ga <= 1)
            for i in np.where(bajo)[0]:
                t = tau(gh[i], ga[i], l[i], m[i], rho)
                corr[i] = max(t, 1e-6)
            ll = ll + w * np.log(corr)
        pen = ridge * (np.sum(atk ** 2) + np.sum(dfn ** 2))
        return -(ll.sum()) + pen

    p0 = np.zeros(2 * n + 1)
    p0[2 * n - 2] = np.log(max(np.mean(np.concatenate([sL, sV])), .3))   # nivel
    p0[2 * n - 1] = 0.40     # ventaja de local inicial
    p0[2 * n]     = -0.10    # rho inicial
    lim = [(-1.5, 1.5)] * (2 * n - 2) + [(-2.0, 1.5)] + [(-0.3, 1.2)] + \
          ([(rho_fijo, rho_fijo)] if rho_fijo is not None else [(-0.25, 0.25)])
    r = minimize(neg, p0, method='L-BFGS-B', bounds=lim,
                 options={'maxiter': 1200, 'ftol': 1e-9})
    atk, dfn, mu, casa, rho = desarmar(r.x)
    return {'atk': dict(zip(equipos, atk)), 'dfn': dict(zip(equipos, dfn)),
            'mu': mu, 'casa': casa, 'rho': rho}


def predecir(mod, h, a):
    if h not in mod['atk'] or a not in mod['atk']:
        return (.45, .30, .25)
    l = float(np.clip(np.exp(mod['mu'] + mod['casa'] + mod['atk'][h] - mod['dfn'][a]), .05, 8))
    m = float(np.clip(np.exp(mod['mu'] + mod['atk'][a] - mod['dfn'][h]), .05, 8))
    return a_1x2(matriz(l, m, mod['rho']))


# ---------------------------------------------------------------- metricas
def logloss(ps, res):
    return -np.mean([np.log(max(p[r], 1e-9)) for p, r in zip(ps, res)])


def rps(ps, res):
    """Ranked Probability Score: castiga menos errar por poco."""
    tot = 0
    for p, r in zip(ps, res):
        obs = [0, 0, 0]; obs[r] = 1
        cp = cr = 0; s = 0
        for i in range(2):
            cp += p[i]; cr += obs[i]; s += (cp - cr) ** 2
        tot += s / 2
    return tot / len(ps)


def resultado(r):
    gh, ga = r['home_team_goal_count'], r['away_team_goal_count']
    return 0 if gh > ga else (1 if gh == ga else 2)


def del_mercado(r):
    o = np.array([r['odds_ft_home_team_win'], r['odds_ft_draw'], r['odds_ft_away_team_win']])
    if np.any(o <= 1.01) or np.any(pd.isna(o)):
        return None
    p = 1 / o
    return p / p.sum()


# ---------------------------------------------------------------- validacion
def caminar(j, mezcla, xi, ridge, rho_fijo=None, desde=0.45, cada=12):
    """
    Validacion hacia adelante: se reajusta cada tantos partidos y se predice
    solo lo que el modelo no vio.
    """
    equipos = sorted(set(j['ih']) | set(j['ia']))
    ini = int(len(j) * desde)
    ps, res = [], []
    mod = None
    for i in range(ini, len(j)):
        if mod is None or (i - ini) % cada == 0:
            mod = ajustar(j.iloc[:i], equipos, mezcla, xi, ridge, rho_fijo)
        r = j.iloc[i]
        ps.append(predecir(mod, r['ih'], r['ia']))
        res.append(resultado(r))
    return ps, res, j.iloc[ini:]
