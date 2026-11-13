# Resumen del experimento

Semilla 0 · 20 niveles generados por familia · 60000 iteraciones · 20 % de niveles reales para prueba

Reales = niveles hechos a mano que el modelo NO usó para ajustarse. p = prueba de Mann-Whitney (p < 0,05: diferencia significativa). δ = delta de Cliff (generados frente a reales; |δ| < 0,15 despreciable, < 0,33 pequeña, < 0,47 mediana, mayor: grande).


## Con río

| Métrica | Reales: media ± DE (n) | Generados: media ± DE (n) | p | δ |
|---|---|---|---|---|
| Tiempo de generación (s) | – | 21.8 ± 3.4 (20) | – | – |
| Objetos por nivel | 160 ± 23 (11) | 167 ± 26 (20) | 0.396 | 0.19 |
| Pares de objetos atravesados | 23.09 ± 20.14 (11) | 10.60 ± 7.47 (20) | 0.116 | -0.35 |
| Pérdida estadística | 7837.7 ± 3280.3 (11) | 7741.2 ± 4673.3 (20) | 0.885 | -0.04 |
| Novedad (distancia al nivel de ajuste más parecido) | 12.56 ± 1.25 (11) | 12.29 ± 1.47 (20) | 0.757 | -0.07 |
| Densidad de ocupación | 0.145 ± 0.028 (11) | 0.140 ± 0.036 (20) | 0.522 | -0.15 |
| Fracción de agua | 0.133 ± 0.127 (11) | 0.142 ± 0.076 (20) | 0.154 | 0.32 |
| Puentes que tocan el agua | 0.82 ± 0.34 (11) | 0.93 ± 0.23 (19) | 0.246 | 0.17 |
| Puentes que cruzan el río | 0.52 ± 0.48 (11) | 0.26 ± 0.43 (19) | 0.105 | -0.33 |
| Relaciones de cercanía por objeto | 0.52 ± 0.20 (11) | 0.57 ± 0.17 (20) | 0.445 | 0.17 |
| Relaciones de apilamiento por objeto | 0.058 ± 0.033 (11) | 0.036 ± 0.021 (20) | 0.055 | -0.43 |
| Relaciones laterales por objeto | 4.96 ± 0.83 (11) | 5.13 ± 1.11 (20) | 0.606 | 0.12 |
| Relaciones frontales por objeto | 3.30 ± 0.55 (11) | 3.51 ± 0.74 (20) | 0.312 | 0.23 |
| Diversidad entre niveles del grupo | 15.32 (11) | 15.92 (20) | | |

Niveles generados sin objetos atravesados: 0 de 20 (0 %).

## Sin río

| Métrica | Reales: media ± DE (n) | Generados: media ± DE (n) | p | δ |
|---|---|---|---|---|
| Tiempo de generación (s) | – | 24.4 ± 2.3 (20) | – | – |
| Objetos por nivel | 159 ± 15 (11) | 165 ± 14 (20) | 0.247 | 0.26 |
| Pares de objetos atravesados | 9.91 ± 7.18 (11) | 0.55 ± 1.79 (20) | 0.000 | -0.95 |
| Pérdida estadística | 8463.1 ± 4884.8 (11) | 4877.1 ± 3013.1 (20) | 0.018 | -0.53 |
| Novedad (distancia al nivel de ajuste más parecido) | 10.43 ± 1.90 (11) | 11.70 ± 0.71 (20) | 0.143 | 0.33 |
| Densidad de ocupación | 0.176 ± 0.049 (11) | 0.153 ± 0.028 (20) | 0.180 | -0.30 |
| Fracción de agua | 0.000 ± 0.000 (11) | 0.000 ± 0.000 (20) | – | 0.00 |
| Relaciones de cercanía por objeto | 0.36 ± 0.06 (11) | 0.33 ± 0.14 (20) | 0.223 | -0.27 |
| Relaciones de apilamiento por objeto | 0.010 ± 0.011 (11) | 0.009 ± 0.013 (20) | 0.540 | -0.14 |
| Relaciones laterales por objeto | 4.36 ± 0.59 (11) | 4.33 ± 0.74 (20) | 0.885 | -0.04 |
| Relaciones frontales por objeto | 3.10 ± 0.39 (11) | 2.91 ± 0.56 (20) | 0.167 | -0.31 |
| Diversidad entre niveles del grupo | 13.99 (11) | 13.93 (20) | | |

Niveles generados sin objetos atravesados: 16 de 20 (80 %).
