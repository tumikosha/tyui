# `we` — консольная точка входа в редактор

**Дата:** 2026-05-30
**Ветка:** feature/console
**Статус:** дизайн согласован, ожидает ревью спеки

## Цель

Отдельная консольная команда:

```
we <filename_1> <filename_2> ...
```

открывает по окну редактора на каждый файл. Окна — полного размера (на весь
экран), сложены каскадом со сдвигом на несколько символов сверху и слева.
Первый файл-аргумент оказывается сверху и в фокусе.

## Решения (зафиксированы при брейнсторме)

| Вопрос | Решение |
|--------|---------|
| Форма команды | Отдельный script `we` в PATH (новый entry point) |
| Состав десктопа | Редакторы поверх **скрытых** панелей FM (как нынешний editor-режим) |
| Геометрия каскада | Окна одинакового **уменьшенного** размера; нижний-правый угол последнего прижат к углу экрана; уголки выглядывают лесенкой в правый-нижний угол (классика Turbo Vision/MDI) |
| Порядок/фокус | Первый файл (`a.py`) сверху по z-order и в фокусе, offset (0,0) |
| Величина сдвига | `DX = 2` колонки, `DY = 1` строка на каждый следующий файл |
| Директория в аргументах | Пропускать |

## Архитектура

Изменения локализованы в трёх точках: `pyproject.toml`, `tyui/main.py`,
`tyui/app.py`. Новый `launch_mode = "we"`.

### 1. Точка входа

`pyproject.toml`:

```toml
[project.scripts]
tyui = "tyui.main:main"
we   = "tyui.main:main_we"
```

`tyui/main.py` — новая функция `main_we()`:

- Парсит `sys.argv[1:]` как список позиционных путей (`nargs="*"`).
- Зовёт `TyuiApp(launch_mode="we", initial_paths=[...]).run()`.

`main()` и его `_parse_args`/`_resolve_launch_mode` не трогаем — `we` идёт
отдельным путём.

### 2. Конструктор приложения

`TyuiApp.__init__` получает новый необязательный параметр:

```python
initial_paths: list[str | Path] | None = None
```

Хранится как `self.initial_paths: list[Path]` (пустой список, если не задан).
Существующий `initial_path` остаётся для режимов `fm`/`editor`/`cli` — обратная
совместимость не нарушается. `LaunchMode` расширяется значением `"we"`.

`_panel_cwd()` для режима `we` не меняется: `initial_path` пуст → скрытые
панели сидят в `Path.cwd()` (то есть в каталоге, откуда запущен `we`).

### 3. Рефакторинг создания окна редактора

Из `_open_editor_window` выделяется хелпер с единственной ответственностью —
собрать окно редактора:

```python
def _make_editor_window(
    self, path: Path, *, position: tuple[int, int],
    size: tuple[int, int], maximized: bool, win_id: str,
) -> Window:
    text = path.read_text() if path.exists() else ""
    content = _FocusableEditorContent(initial_text=text, file_path=str(path))
    win = make_window(
        content, title=path.name, position=position, size=size,
        decorations=Decorations(close_box=True, zoom_box=True,
                                 minimize_box=True, resize_grip=True),
        id=win_id,
    )
    return win
```

`_open_editor_window` переписывается поверх этого хелпера (его текущая ветка
viewer/hex остаётся как есть — хелпер покрывает только редактируемый случай).
Цель рефактора — один источник правды для конструирования editor-окна.

### 4. Монтирование каскада

Ветка в `_mount_initial_windows`:

```python
if self.launch_mode == "we":
    self._add_panel_windows(cwd, visible=False)   # скрытые панели
    self._mount_cascaded_editors()
    return
```

`_mount_cascaded_editors()`:

1. Фильтрует `self.initial_paths`: директории пропускаются (со statusbar-
   уведомлением вида `skipped <dir>: not a file`). Несуществующие пути
   **сохраняются** — они откроются пустым буфером с этим `file_path`.
2. Если после фильтра список пуст → одно untitled-окно (пустой
   `_FocusableEditorContent`, `file_path=None`).
3. Считает общий размер окна каскада (одинаковый для всех):
   - `N = len(files)`, `W, H = desktop.usable_size`
   - `cw = max(_WE_MIN_W, W - (N - 1) * _WE_CASCADE_DX)`
   - `ch = max(_WE_MIN_H, H - (N - 1) * _WE_CASCADE_DY)`
   Так нижний-правый угол **последнего** окна (`i = N-1`) садится ровно в угол
   десктопа `(W, H)`; при одном файле `cw, ch = W, H` (на весь экран).
4. Для каждого файла с индексом `i`:
   - `position = (i * _WE_CASCADE_DX, i * _WE_CASCADE_DY)`
   - `size = (cw, ch)` — одинаковый уменьшенный размер.
   - `maximized = False`, `win_id = f"editor-{seq}"` (через `_editor_seq`).
5. **Порядок добавления — обратный** (последний файл первым), чтобы первый
   файл-аргумент добавился последним → оказался сверху по z-order и получил
   фокус, в offset (0,0). Уголки окон `1..N-1` выглядывают лесенкой в
   правый-нижний угол из-под верхнего окна.

Константы модуля:

```python
_WE_CASCADE_DX = 2
_WE_CASCADE_DY = 1
_WE_MIN_W = 20   # пол для размера при большом числе файлов
_WE_MIN_H = 6
```

### 5. Resize и layout

`_apply_default_layout` уже делает `return` при `launch_mode != "fm"`, поэтому
ресайз терминала не перекладывает каскад. Пересчёт каскада на resize — вне
скоупа (YAGNI).

## Поток данных

```
shell:  we a.py b.py c.py
  → main_we() → initial_paths=[a.py, b.py, c.py]
  → TyuiApp(launch_mode="we")
  → on_mount → _mount_initial_windows
      → _add_panel_windows(cwd, visible=False)
      → _mount_cascaded_editors()
          N=3, size=(W-4, H-2) для всех окон
          add c.py @ (4,2)   ← нижний-правый угол в (W,H)
          add b.py @ (2,1)
          add a.py @ (0,0)   ← сверху, в фокусе
```

Итоговый z-order (сверху вниз): a.py, b.py, c.py. На экране: a.py сверху
(offset 0,0), из-под него лесенкой в правый-нижний угол выглядывают уголки
b.py и c.py; нижний-правый угол c.py прижат к углу экрана.

## Обработка ошибок / краевые случаи

- **Нет аргументов** (`we`): одно пустое untitled-окно.
- **Несуществующий файл**: пустой буфер, `file_path` проставлен, Ctrl+S создаёт
  файл по этому пути.
- **Директория в аргументах**: пропускается с уведомлением в statusbar.
- **Нечитаемый файл** (`OSError` на `read_text`): пустой текст (как в нынешнем
  `_open_editor_window`).
- **Все аргументы отфильтрованы** (только директории): откатываемся к пустому
  untitled-окну.

## Тесты

Async smoke-тесты по образцу `tests/fm/test_app_skeleton.py`, новый файл
`tests/fm/test_we_mode.py`:

1. `we a b c` (3 реальных файла) → 3 окна `editor-*` + 2 скрытые панели;
   z-top и Textual-фокус на первом файле; offset'ы окон по файлам =
   (0,0), (2,1), (4,2); все окна одного размера; нижний-правый угол окна
   последнего файла = `usable_size` (прижат к углу).
2. Несуществующий файл → окно с пустым буфером и корректным `file_path`.
3. `we` без аргументов → ровно одно untitled editor-окно.
4. Директория среди аргументов → пропущена, число editor-окон = числу файлов.
5. Юнит на `main_we()`: резолвит список путей и `launch_mode="we"`
   (через монтирование с фейковым argv / прямой вызов резолвера).

## Вне скоупа

- Пересчёт каскада при resize терминала.
- Настраиваемые `DX`/`DY` через конфиг.
- Открытие директории как редактора.
- Tile-раскладка по умолчанию для `we` (доступна вручную через меню `Cascade`/
  `Tile`).
```
