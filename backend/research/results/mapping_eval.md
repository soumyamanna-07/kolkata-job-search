# Subject-to-skill mapping: evaluation

Test set: 73 subjects, 6 correct (subject, skill) pairs, 67 subjects that teach no listed job skill. Labelled by: project author (checked).

| Method | Precision | Recall | F1 (95% CI) | Empty subjects left empty |
|---|---|---|---|---|
| named | 0.00 | 0.00 | 0.00 (0.00-0.00) | 61/67 |
| table | 0.05 | 0.67 | 0.10 (0.02-0.20) | 44/67 |
| rules | 0.05 | 0.67 | 0.10 (0.02-0.19) | 44/67 |
| ai only | 0.00 | 0.00 | 0.00 (0.00-0.00) | 65/67 |
| system | 0.05 | 0.67 | 0.10 (0.02-0.19) | 44/67 |
| system, weight >= 0.6 | 0.06 | 0.33 | 0.10 (0.00-0.24) | 49/67 |
| system, weight >= 0.9 | 0.15 | 0.33 | 0.21 (0.00-0.47) | 58/67 |

Precision/recall/F1 are micro-averaged over (subject, skill) pairs; the interval is a 2000-round bootstrap over subjects (seed 7).
