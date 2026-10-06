# Конвейер

| шаг | команда | статус после | артефакты (`data/studio/videos/{id}/`) |
|---|---|---|---|
| тема | `studio topic add/import` | — | БД `topics` |
| сценарий | `studio script new TOPIC` | `script_review` | `script.yaml`, `versions/script.vN.yaml`, `validation.json` |
| правка | `studio script export/import` | `script_review` (v+1, approve снят) | то же |
| approve | `studio script approve` | `approved` | `approved.json` |
| рендер | `studio render ID` | `voicing → rendering → assembling → final_review` | см. ниже |
| ревью | `studio review ID approve --thumb B` / `reject` | `final_review` (+одобрено) / `rejected` | — |
| публикация | `studio publish ID` | `scheduled` | `publish.json`, `exports/` при ошибке миниатюры |
| выход | `studio track` | `published` | БД `stats_snapshots` |

Ошибка любого этапа → `failed` (`studio status ID` покажет этап, тип, сообщение, retryable) → `studio retry ID`.

## Артефакты рендера
```
scenes/{scene_id}/narration.wav  words.json  narration.json  visual_16x9.mp4  [visual_9x16.mp4]
                  segment_16x9.mp4  [segment_9x16.mp4 short_hook.wav endcard_9x16.mp4]  manifest.json
long.mp4  captions.srt  chapters.txt  assembly.json  meta.json  preview.mp4  final_review.json
thumbs/A.jpg B.jpg C.jpg thumbs.json
shorts/short-{scene}/final.mp4  captions.ass  short.json
manifest.json
```
Служебные сцены `hook` и `outro` — слайды (ADR 0002). 9:16 — только для кандидатов в шортсы.

## Тайминг
Сцена = max(озвучка + 0.3 с до + 0.5 с после, `min_sec`, минимум визуала). Визуал короче — freeze
последнего кадра, длиннее — обрезка хвоста (для терминала хвост — финальный `Sleep`). Голос не режется.
Шортс = [карточка хука с озвучкой `short_hook`] + сцена + end-card 2 с; > 60 с — пропуск с предупреждением.
