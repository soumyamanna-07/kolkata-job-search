# Subject-to-skill mapping: evaluation

Test set: 64 subjects, 79 correct (subject, skill) pairs, 30 subjects that teach no listed job skill. Labelled by: project author (checked).

| Method | Precision | Recall | F1 (95% CI) | Empty subjects left empty |
|---|---|---|---|---|
| named | 0.97 | 0.39 | 0.56 (0.41-0.69) | 30/30 |
| table | 0.53 | 0.80 | 0.64 (0.53-0.73) | 22/30 |
| rules | 0.56 | 0.90 | 0.69 (0.59-0.77) | 22/30 |
| ai only | 0.90 | 0.11 | 0.20 (0.09-0.33) | 30/30 |
| system | 0.56 | 0.90 | 0.69 (0.59-0.77) | 22/30 |
| system, weight >= 0.6 | 0.77 | 0.78 | 0.77 (0.69-0.84) | 26/30 |
| system, weight >= 0.9 | 0.96 | 0.54 | 0.69 (0.58-0.79) | 29/30 |

Precision/recall/F1 are micro-averaged over (subject, skill) pairs; the interval is a 2000-round bootstrap over subjects (seed 7).
