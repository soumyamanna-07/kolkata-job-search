# Subject-to-skill mapping: evaluation

Test set: 64 subjects, 79 correct (subject, skill) pairs, 30 subjects that teach no listed job skill. Labelled by: project author (checked).

| Method | Precision | Recall | F1 (95% CI) | Empty subjects left empty |
|---|---|---|---|---|
| named | 0.97 | 0.39 | 0.56 (0.41-0.69) | 30/30 |
| table | 0.55 | 0.80 | 0.65 (0.55-0.74) | 22/30 |
| rules | 0.58 | 0.90 | 0.70 (0.60-0.78) | 22/30 |
| ai only | 0.90 | 0.11 | 0.20 (0.09-0.33) | 30/30 |
| system | 0.58 | 0.90 | 0.70 (0.60-0.78) | 22/30 |
| system, weight >= 0.6 | 0.79 | 0.78 | 0.79 (0.71-0.85) | 26/30 |
| system, weight >= 0.9 | 0.96 | 0.54 | 0.69 (0.58-0.79) | 29/30 |

Precision/recall/F1 are micro-averaged over (subject, skill) pairs; the interval is a 2000-round bootstrap over subjects (seed 7).

## AI similarity cut-off (system)

| Cut-off | Precision | Recall | F1 | Empty subjects left empty | Skills added by AI |
|---|---|---|---|---|---|
| 0.30 | 0.50 | 0.91 | 0.65 | 13/30 | 20 |
| 0.35 | 0.54 | 0.90 | 0.68 | 16/30 | 8 |
| 0.40 | 0.57 | 0.90 | 0.70 | 21/30 | 1 |
| 0.45 | 0.58 | 0.90 | 0.70 | 22/30 | 0 |
| 0.50 (now) | 0.58 | 0.90 | 0.70 | 22/30 | 0 |
| 0.55 | 0.58 | 0.90 | 0.70 | 22/30 | 0 |
| 0.60 | 0.58 | 0.90 | 0.70 | 22/30 | 0 |
