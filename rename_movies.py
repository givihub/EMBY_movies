#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт переименования фильмов по NFO файлам для Emby (GiviMedia)
=================================================================

Логика именования:
  - Российский (только РФ/СССР в странах И title==originaltitle): "Название год"
  - Зарубежный (названия разные): "OriginalTitle (Title) год"
  - При неоднозначности (нет стран, названия совпадают) — спрашивает
  - Конфликт имён → добавляет (1), (2)...

Типы папок:
  1. Одиночный фильм в папке → переименовать папку и файлы
  2. Фильм без папки в корне → создать папку, переместить файлы
  3. Папка с _ → сборник: зайти внутрь и обработать подпапки
  4. Папка без _ с несколькими подпапками/NFO → добавить _ и обработать

Что переименовывается внутри папки фильма:
  - Папка фильма, видеофайл, NFO, субтитры
  - NFO обновляется: lockdata=true, lockedfields добавляются

Что НЕ переименовывается (только перемещается):
  - poster.jpg, fanart*.jpg, landscape.jpg, clearlogo.png и т.д.

Запуск:
  python rename_movies.py D:\\Media\\Movies            # preview
  python rename_movies.py D:\\Media\\Movies --apply    # применить
"""

import sys
import re
import xml.etree.ElementTree as ET
import csv
import shutil
from pathlib import Path
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
# Настройки
# ═══════════════════════════════════════════════════════════════════

VIDEO_EXTENSIONS  = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.m4v', '.ts', '.flv', '.webm', '.m4v'}
RENAME_WITH_MOVIE = {'.nfo', '.srt', '.ass', '.ssa', '.sub', '.idx', '.sup'}
INVALID_CHARS     = re.compile(r'[\\/:*?"<>|]')
RUSSIAN_COUNTRIES = {'россия', 'russia', 'ссср', 'ussr', 'soviet union', 'советский союз'}
LOCKED_FIELDS     = 'Name|OriginalTitle|SortName|Overview|Genres|Cast'

ART_NAMES = {
    'poster.jpg', 'poster.png', 'fanart.jpg', 'fanart.png',
    'fanart1.jpg', 'fanart2.jpg', 'fanart3.jpg', 'fanart4.jpg',
    'fanart5.jpg', 'fanart6.jpg', 'fanart7.jpg', 'fanart8.jpg',
    'landscape.jpg', 'landscape.png', 'clearlogo.png', 'clearlogo.jpg',
    'clearart.png', 'clearart.jpg', 'banner.jpg', 'banner.png',
    'thumb.jpg', 'disc.jpg', 'back.jpg', 'back.png',
}


# ═══════════════════════════════════════════════════════════════════
# Утилиты
# ═══════════════════════════════════════════════════════════════════

def sanitize(name: str) -> str:
    name = INVALID_CHARS.sub('', name)
    return name.strip('. ')


def parse_nfo(nfo_path: Path):
    """Парсит NFO фильма. Возвращает dict или None."""
    try:
        content = nfo_path.read_text(encoding='utf-8', errors='replace')
        root = ET.fromstring(content)
    except Exception:
        return None
    if root.tag != 'movie':
        return None

    def get(tag):
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else ''

    return {
        'title':         get('title'),
        'originaltitle': get('originaltitle'),
        'year':          get('year'),
        'countries':     [c.text.strip().lower() for c in root.findall('country') if c.text],
        'root':          root,
        'nfo_path':      nfo_path,
    }


def is_russian(info: dict):
    """
    True  — российский: только РФ/СССР в странах И названия совпадают
    False — зарубежный: названия разные, или есть иностранные страны
    None  — неоднозначно: нет стран, названия совпадают → спросим
    """
    title = info['title'].lower()
    orig  = info['originaltitle'].lower()

    # Названия явно разные → всегда зарубежный
    if orig and orig != title:
        return False

    has_russia  = any(c in RUSSIAN_COUNTRIES for c in info['countries'])
    has_other   = any(c not in RUSSIAN_COUNTRIES for c in info['countries'])
    only_russia = has_russia and not has_other

    if only_russia:
        return True   # только РФ/СССР → российский

    if info['countries'] and not has_russia:
        return False  # есть страны, но не российские → зарубежный

    # Нет стран → неоднозначно
    return None


def build_name(info: dict) -> str:
    """Формирует итоговое имя папки/файла. При неоднозначности спрашивает."""
    title = sanitize(info['title'])
    orig  = sanitize(info['originaltitle'])
    year  = info['year'] or 'unknown'
    ru    = is_russian(info)

    if ru is None:
        # Названия совпадают или originaltitle пустой → автоматически российский
        if not orig or orig.lower() == title.lower():
            ru = True
        else:
            print(f"\n  ⚠️  Неоднозначность:")
            print(f"     title='{title}', originaltitle='{orig}', страны={info['countries']}")
            print(f"     [1] {title} {year}  (российский)")
            print(f"     [2] {orig} ({title}) {year}  (зарубежный)")
            choice = input("     Выберите [1/2] (Enter=1): ").strip()
            ru = (choice != '2')

    if ru:
        return f"{title} {year}"
    else:
        if orig and orig.lower() != title.lower():
            return f"{orig} ({title}) {year}"
        else:
            return f"{title} {year}"


def unique_name(base: str, taken: set) -> str:
    if base not in taken:
        return base
    i = 1
    while f"{base} ({i})" in taken:
        i += 1
    return f"{base} ({i})"


def patch_nfo(nfo_path: Path):
    """Обновляет lockdata=true и lockedfields в NFO."""
    try:
        content = nfo_path.read_text(encoding='utf-8', errors='replace')
        root = ET.fromstring(content)
    except Exception:
        return

    changed = False
    ld = root.find('lockdata')
    if ld is None:
        ld = ET.SubElement(root, 'lockdata')
        ld.text = 'true'
        changed = True
    elif ld.text != 'true':
        ld.text = 'true'
        changed = True

    lf = root.find('lockedfields')
    if lf is None:
        lf = ET.Element('lockedfields')
        lf.text = LOCKED_FIELDS
        pos = 0
        for i, child in enumerate(list(root)):
            if child.tag in ('outline', 'lockdata'):
                pos = i + 1
        root.insert(pos, lf)
        changed = True
    elif lf.text != LOCKED_FIELDS:
        lf.text = LOCKED_FIELDS
        changed = True

    if changed:
        xml_str = ET.tostring(root, encoding='unicode')
        nfo_path.write_text(
            '<?xml version="1.0" encoding="utf-8" standalone="yes"?>' + xml_str,
            encoding='utf-8'
        )


# ═══════════════════════════════════════════════════════════════════
# Анализ структуры папки
# ═══════════════════════════════════════════════════════════════════

def classify_dir(d: Path):
    """
    Возвращает тип папки:
      'collection'  — папка сборника (начинается с _ или содержит подпапки с NFO)
      'single'      — папка одного фильма (содержит ровно один NFO в корне)
      'unknown'     — нет NFO вообще
    """
    if d.name.startswith('_'):
        return 'collection'

    # NFO прямо в папке
    direct_nfos = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() == '.nfo']
    # Подпапки с NFO внутри
    subdirs_with_nfo = [
        sd for sd in d.iterdir()
        if sd.is_dir() and any(f.suffix.lower() == '.nfo' for f in sd.iterdir() if f.is_file())
    ]

    if subdirs_with_nfo and (len(subdirs_with_nfo) > 1 or not direct_nfos):
        return 'collection'

    if direct_nfos:
        return 'single'

    return 'unknown'


def find_movie_nfo(folder: Path):
    """Ищет NFO фильма в папке (не tvshow, не episodedetails)."""
    for nfo in folder.glob('*.nfo'):
        info = parse_nfo(nfo)
        if info:
            return nfo, info
    return None, None


def find_video(folder: Path):
    """Ищет первый видеофайл в папке."""
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            return f
    return None


def find_related_files(base_dir: Path, base_stem: str):
    """Связанные файлы для фильмов без папки (арт с дефисом, субтитры)."""
    related = []
    for f in base_dir.iterdir():
        if not f.is_file() or f.suffix.lower() == '.nfo':
            continue
        if f.stem == base_stem and f.suffix.lower() in (RENAME_WITH_MOVIE - {'.nfo'}):
            related.append(('rename', f))
        elif f.name.startswith(base_stem + '-'):
            related.append(('move_as_is', f))
    return related


# ═══════════════════════════════════════════════════════════════════
# Сбор плана
# ═══════════════════════════════════════════════════════════════════

def collect_plan(base_dir: Path):
    """
    Анализирует base_dir и возвращает список операций.
    Каждая операция: dict с ключами type, ...
    """
    plan       = []
    taken      = {item.name for item in base_dir.iterdir() if item.is_dir()}
    no_nfo     = []

    for item in sorted(base_dir.iterdir()):
        # ── Файлы без папки ──────────────────────────────────────────
        if item.is_file() and item.suffix.lower() == '.nfo':
            info = parse_nfo(item)
            if not info:
                continue
            new_base = build_name(info)
            if base_dir / new_base == item.parent / new_base:
                # уже правильно назван — пропуск невозможен (файл, не папка)
                pass
            new_base = unique_name(new_base, taken)
            taken.add(new_base)

            video = None
            for ext in VIDEO_EXTENSIONS:
                candidate = item.with_suffix(ext)
                if candidate.exists():
                    video = candidate
                    break

            plan.append({
                'type':     'no_folder',
                'nfo':      item,
                'info':     info,
                'video':    video,
                'new_base': new_base,
                'base_dir': base_dir,
                'skip':     False,
            })
            continue

        if not item.is_dir():
            continue

        kind = classify_dir(item)

        # ── Сборник (начинается с _ или несколько подпапок) ──────────
        if kind == 'collection':
            # Если папка не начинается с _ — добавляем _
            new_collection_name = item.name if item.name.startswith('_') else '_' + item.name
            sub_taken = {sd.name for sd in item.iterdir() if sd.is_dir()}

            sub_ops = []

            # 1) Подпапки с фильмами
            for subitem in sorted(item.iterdir()):
                if not subitem.is_dir():
                    continue
                sub_nfo, sub_info = find_movie_nfo(subitem)
                if not sub_info:
                    no_nfo.append(str(subitem))
                    continue
                sub_new = build_name(sub_info)
                already_correct = (subitem.name == sub_new)
                if not already_correct:
                    sub_new = unique_name(sub_new, sub_taken)
                    sub_taken.add(sub_new)

                sub_ops.append({
                    'folder':   subitem,
                    'nfo':      sub_nfo,
                    'info':     sub_info,
                    'video':    find_video(subitem),
                    'new_base': sub_new,
                    'skip':     already_correct,
                    'no_folder': False,
                })

            # 2) NFO прямо в корне сборника (фильмы вперемешку без подпапок)
            for subfile in sorted(item.iterdir()):
                if not subfile.is_file() or subfile.suffix.lower() != '.nfo':
                    continue
                sub_info = parse_nfo(subfile)
                if not sub_info:
                    continue
                sub_new = build_name(sub_info)
                sub_new = unique_name(sub_new, sub_taken)
                sub_taken.add(sub_new)

                # Ищем видео с тем же базовым именем
                sub_video = None
                for ext in VIDEO_EXTENSIONS:
                    candidate = subfile.with_suffix(ext)
                    if candidate.exists():
                        sub_video = candidate
                        break

                sub_ops.append({
                    'folder':    None,
                    'nfo':       subfile,
                    'info':      sub_info,
                    'video':     sub_video,
                    'new_base':  sub_new,
                    'skip':      False,
                    'no_folder': True,
                    'base_dir':  item,  # корень сборника
                })

            plan.append({
                'type':             'collection',
                'folder':           item,
                'new_folder_name':  new_collection_name,
                'rename_folder':    item.name != new_collection_name,
                'sub_ops':          sub_ops,
            })
            continue

        # ── Одиночный фильм в папке ───────────────────────────────────
        if kind == 'single':
            nfo, info = find_movie_nfo(item)
            if not info:
                no_nfo.append(str(item))
                continue
            new_base = build_name(info)
            already_correct = (item.name == new_base)
            if not already_correct:
                new_base = unique_name(new_base, taken)
                taken.add(new_base)

            plan.append({
                'type':     'in_folder',
                'folder':   item,
                'nfo':      nfo,
                'info':     info,
                'video':    find_video(item),
                'new_base': new_base,
                'base_dir': base_dir,
                'skip':     already_correct,
            })
            continue

        # ── Нет NFO ───────────────────────────────────────────────────
        no_nfo.append(str(item))

    return plan, no_nfo


# ═══════════════════════════════════════════════════════════════════
# Preview
# ═══════════════════════════════════════════════════════════════════

def print_plan(plan, no_nfo, base_dir):
    if no_nfo:
        print(f"\n⚠️  Папки/файлы без NFO (пропущены): {len(no_nfo)}")
        for p in no_nfo:
            print(f"   {Path(p).name}")

    print(f"\n{'═'*65}")
    print("📋  ПЛАН ПЕРЕИМЕНОВАНИЯ")
    print(f"{'═'*65}")

    changed = unchanged = 0

    for op in plan:
        if op['type'] == 'collection':
            # Подсчёт
            sub_changed   = [s for s in op['sub_ops'] if not s['skip']]
            sub_unchanged = [s for s in op['sub_ops'] if s['skip']]
            changed   += len(sub_changed) + (1 if op['rename_folder'] else 0)
            unchanged += len(sub_unchanged)

            coll_arrow = f"→ 📁 {op['new_folder_name']}/" if op['rename_folder'] else f"📁 {op['folder'].name}/ (без изменений)"
            print(f"\n  🗂️  {op['folder'].name}")
            print(f"     {coll_arrow}")
            for s in sub_changed:
                if s.get('no_folder'):
                    vname = s['video'].name if s['video'] else '(нет видео)'
                    print(f"       📄 {vname}  [без подпапки]")
                    print(f"          → создать 📁 {s['new_base']}/")
                else:
                    print(f"       📁 {s['folder'].name}")
                    print(f"          → {s['new_base']}/")
                if s['video']:
                    print(f"             {s['video'].name} → {s['new_base']}{s['video'].suffix}")
                print(f"             {s['nfo'].name} → {s['new_base']}.nfo")
            if sub_unchanged:
                print(f"       ✓ {len(sub_unchanged)} фильмов уже названы правильно")

        elif op['type'] == 'in_folder':
            if op['skip']:
                unchanged += 1
            else:
                changed += 1
                print(f"\n  📁 {op['folder'].name}")
                print(f"     → 📁 {op['new_base']}/")
                if op['video']:
                    print(f"        {op['video'].name} → {op['new_base']}{op['video'].suffix}")
                print(f"        {op['nfo'].name} → {op['new_base']}.nfo")

        elif op['type'] == 'no_folder':
            changed += 1
            vname = op['video'].name if op['video'] else '(видео не найдено!)'
            print(f"\n  📄 {vname}  [без папки]")
            print(f"     → создать 📁 {op['new_base']}/")
            if op['video']:
                print(f"        → {op['new_base']}{op['video'].suffix}")
            print(f"        {op['nfo'].name} → {op['new_base']}.nfo")
            for kind, f in find_related_files(base_dir, op['nfo'].stem):
                art = f.name[len(op['nfo'].stem)+1:] if kind == 'move_as_is' else op['new_base'] + f.suffix
                print(f"        {f.name} → {art}")

    print(f"\n{'═'*65}")
    print(f"  Изменений: {changed}  |  Без изменений: {unchanged}")
    print(f"{'═'*65}\n")


# ═══════════════════════════════════════════════════════════════════
# Применение
# ═══════════════════════════════════════════════════════════════════

def apply_plan(plan, base_dir, writer):
    errors = []

    for op in plan:
        if op['type'] == 'collection':
            # Переименовываем папку сборника если нужно
            new_coll = base_dir / op['new_folder_name']
            if op['rename_folder']:
                try:
                    op['folder'].rename(new_coll)
                    writer.writerow(['сборник', op['folder'].name, op['new_folder_name'], 'OK'])
                    # Обновляем пути sub_ops
                    for s in op['sub_ops']:
                        rel = s['folder'].relative_to(op['folder'])
                        s['folder'] = new_coll / rel
                        s['nfo']    = new_coll / s['nfo'].relative_to(op['folder'])
                        if s['video']:
                            s['video'] = new_coll / s['video'].relative_to(op['folder'])
                except Exception as e:
                    errors.append(f"Сборник {op['folder'].name}: {e}")
                    writer.writerow(['ERROR', op['folder'].name, op['new_folder_name'], str(e)])
                    continue
            else:
                new_coll = op['folder']

            # Обрабатываем подпапки и файлы без папки внутри сборника
            for s in op['sub_ops']:
                if s.get('no_folder'):
                    # Фильм без подпапки внутри сборника
                    err = _apply_no_folder(s, new_coll, writer)
                    if err:
                        errors.append(err)
                elif s['skip']:
                    try:
                        patch_nfo(s['nfo'])
                    except Exception:
                        pass
                else:
                    err = _apply_single(s['folder'], s['new_base'], s['video'], s['nfo'], new_coll, writer)
                    if err:
                        errors.append(err)

        elif op['type'] == 'in_folder':
            if op['skip']:
                try:
                    patch_nfo(op['nfo'])
                except Exception:
                    pass
                continue
            err = _apply_single(op['folder'], op['new_base'], op['video'], op['nfo'], base_dir, writer)
            if err:
                errors.append(err)

        elif op['type'] == 'no_folder':
            err = _apply_no_folder(op, base_dir, writer)
            if err:
                errors.append(err)

    return errors


def _apply_single(folder, new_base, video, nfo, parent_dir, writer):
    """Переименовывает папку одного фильма и файлы внутри."""
    new_folder = parent_dir / new_base
    try:
        # Переименовываем файлы внутри
        for f in list(folder.iterdir()):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if f.name.lower() in ART_NAMES:
                continue
            if ext in VIDEO_EXTENSIONS or ext in RENAME_WITH_MOVIE:
                new_name = new_base + f.suffix
                f.rename(folder / new_name)
                writer.writerow(['файл', f.name, new_name, 'OK'])

        # Переименовываем папку
        folder.rename(new_folder)
        writer.writerow(['папка', folder.name, new_base, 'OK'])

        # Патчим NFO
        nfo_new = new_folder / (new_base + '.nfo')
        if nfo_new.exists():
            patch_nfo(nfo_new)

        return None
    except Exception as e:
        return f"{folder.name} → {new_base}: {e}"


def _apply_no_folder(op, base_dir, writer):
    """Создаёт папку и переносит файлы фильма без папки."""
    new_folder = base_dir / op['new_base']
    try:
        new_folder.mkdir(exist_ok=True)
        old_stem = op['nfo'].stem

        if op['video']:
            dest = new_folder / (op['new_base'] + op['video'].suffix)
            op['video'].rename(dest)
            writer.writerow(['видео', op['video'].name, dest.name, 'OK'])

        dest_nfo = new_folder / (op['new_base'] + '.nfo')
        op['nfo'].rename(dest_nfo)
        patch_nfo(dest_nfo)
        writer.writerow(['nfo', op['nfo'].name, dest_nfo.name, 'OK'])

        for kind, f in find_related_files(base_dir, old_stem):
            if kind == 'rename':
                dest = new_folder / (op['new_base'] + f.suffix)
            else:
                dest = new_folder / f.name[len(old_stem)+1:]
            f.rename(dest)
            writer.writerow([kind, f.name, dest.name, 'OK'])

        return None
    except Exception as e:
        return f"no_folder {op['nfo'].name}: {e}"


# ═══════════════════════════════════════════════════════════════════
# Точка входа
# ═══════════════════════════════════════════════════════════════════

def process(base_dir: Path):
    plan, no_nfo = collect_plan(base_dir)

    if not plan and not no_nfo:
        print("Ничего не найдено.")
        return

    print_plan(plan, no_nfo, base_dir)


    confirm = input("Применить все изменения? [да/нет]: ").strip().lower()
    if confirm not in ('да', 'y', 'yes', 'д'):
        print("Отменено.")
        return

    log_path = base_dir / f"rename_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    with open(log_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Тип', 'Старое', 'Новое', 'Статус'])
        errors = apply_plan(plan, base_dir, writer)

    print(f"\n✅ Готово! Лог: {log_path}")
    if errors:
        print(f"\n❌ Ошибки ({len(errors)}):")
        for e in errors:
            print(f"   {e}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.is_dir():
        print(f"Ошибка: папка не найдена: {target}")
        sys.exit(1)

    if '--apply' not in sys.argv:
        print(f"Использование: python rename_movies.py \"путь к папке\" --apply")
        print(f"Пример:        python rename_movies.py \"M:\\Video\\Movies\" --apply")
        sys.exit(0)

    print(f"📂 Папка:  {target}")
    process(target)
