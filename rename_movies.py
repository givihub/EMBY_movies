#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import re
import xml.etree.ElementTree as ET
import csv
from pathlib import Path
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
# Настройки
# ═══════════════════════════════════════════════════════════════════

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.m4v', '.ts', '.flv', '.webm'}

RENAME_WITH_MOVIE = {'.nfo', '.srt', '.ass', '.ssa', '.sub', '.idx', '.sup'}

# Имена файлов-арта которые НЕ переименовываем (только перемещаем в папку)
ART_NAMES = {
    'poster.jpg', 'poster.png',
    'fanart.jpg', 'fanart.png',
    'fanart1.jpg', 'fanart2.jpg', 'fanart3.jpg', 'fanart4.jpg',
    'fanart5.jpg', 'fanart6.jpg', 'fanart7.jpg', 'fanart8.jpg',
    'landscape.jpg', 'landscape.png',
    'clearlogo.png', 'clearlogo.jpg',
    'clearart.png', 'clearart.jpg',
    'banner.jpg', 'banner.png',
    'thumb.jpg', 'disc.jpg',
}

RUSSIAN_COUNTRIES = {'россия', 'russia', 'ссср', 'ussr', 'soviet union', 'советский союз'}

LOCKED_FIELDS = 'Name|OriginalTitle|SortName|Overview|Genres|Cast'

INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


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

    countries = [c.text.strip().lower() for c in root.findall('country') if c.text]

    return {
        'title':         get('title'),
        'originaltitle': get('originaltitle'),
        'year':          get('year'),
        'countries':     countries,
        'root':          root,
        'nfo_path':      nfo_path,
    }


def is_russian(info: dict):
    """
    True  — точно российский
    False — точно зарубежный
    None  — неоднозначно (спросим)
    """
    title = info['title'].lower()
    orig  = info['originaltitle'].lower()

    for c in info['countries']:
        if c in RUSSIAN_COUNTRIES:
            return True

    if info['countries'] and orig and orig != title:
        return False

    if not orig or orig == title:
        return None

    return None


def build_name(info: dict) -> str:
    """Формирует итоговое имя. При неоднозначности спрашивает."""
    title = sanitize(info['title'])
    orig  = sanitize(info['originaltitle'])
    year  = info['year'] or 'unknown'

    ru = is_russian(info)

    if ru is None:
        print(f"\n  ⚠️  Неоднозначность:")
        print(f"     title='{title}', originaltitle='{orig}', страны={info['countries']}")
        opt1 = f"{title} {year}"
        opt2 = f"{orig} ({title}) {year}" if (orig and orig.lower() != title.lower()) else opt1
        print(f"     [1] {opt1}")
        print(f"     [2] {opt2}")
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
    except Exception as e:
        print(f"    ⚠️  Не удалось прочитать NFO для патча: {e}")
        return

    changed = False

    # lockdata → true
    ld = root.find('lockdata')
    if ld is None:
        ld = ET.SubElement(root, 'lockdata')
        ld.text = 'true'
        changed = True
    elif ld.text != 'true':
        ld.text = 'true'
        changed = True

    # lockedfields — обновляем или создаём
    lf = root.find('lockedfields')
    if lf is None:
        lf = ET.Element('lockedfields')
        lf.text = LOCKED_FIELDS
        children = list(root)
        insert_pos = 0
        for i, child in enumerate(children):
            if child.tag in ('outline', 'lockdata'):
                insert_pos = i + 1
        root.insert(insert_pos, lf)
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
# Поиск фильмов
# ═══════════════════════════════════════════════════════════════════

def find_movies(base_dir: Path):
    movies = []
    no_nfo_folders = []

    # 1) Папки с фильмами
    for subdir in sorted(base_dir.iterdir()):
        if not subdir.is_dir():
            continue

        nfo_files = list(subdir.glob('*.nfo'))
        if not nfo_files:
            no_nfo_folders.append(subdir.name)
            continue

        nfo = nfo_files[0]
        info = parse_nfo(nfo)
        if not info:
            print(f"  ⚠️  Не удалось распознать NFO: {nfo}")
            continue

        video = None
        for f in sorted(subdir.iterdir()):
            if f.suffix.lower() in VIDEO_EXTENSIONS:
                video = f
                break

        movies.append({
            'type':   'in_folder',
            'folder': subdir,
            'video':  video,
            'nfo':    nfo,
            'info':   info,
        })

    # 2) Фильмы без папки (NFO прямо в base_dir)
    for nfo in sorted(base_dir.glob('*.nfo')):
        info = parse_nfo(nfo)
        if not info:
            continue

        video = None
        for ext in VIDEO_EXTENSIONS:
            candidate = nfo.with_suffix(ext)
            if candidate.exists():
                video = candidate
                break

        movies.append({
            'type':   'no_folder',
            'folder': None,
            'video':  video,
            'nfo':    nfo,
            'info':   info,
        })

    if no_nfo_folders:
        print(f"\n⚠️  Папки без NFO (пропущены):")
        for f in no_nfo_folders:
            print(f"   📁 {f}")

    return movies


def find_related_files(base_dir: Path, base_stem: str):
    """
    Находит файлы связанные с фильмом без папки.
    Паттерны: {stem}.srt, {stem}-poster.jpg, {stem}-fanart1.jpg и т.д.
    """
    related = []
    for f in base_dir.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() == '.nfo':
            continue
        # Субтитры и т.д. с точным совпадением stem
        if f.stem == base_stem and f.suffix.lower() in (RENAME_WITH_MOVIE - {'.nfo'}):
            related.append(('rename', f))
            continue
        # Паттерн: stem-что_угодно.ext (арт с дефисом)
        if f.name.startswith(base_stem + '-'):
            related.append(('move_as_is', f))
    return related


# ═══════════════════════════════════════════════════════════════════
# Основная логика
# ═══════════════════════════════════════════════════════════════════

def process(base_dir: Path, apply: bool):
    movies = find_movies(base_dir)

    if not movies:
        print("Фильмы не найдены.")
        return

    print(f"\nНайдено фильмов: {len(movies)}\n")

    taken = set()
    for item in base_dir.iterdir():
        if item.is_dir():
            taken.add(item.name)

    plan = []
    for movie in movies:
        new_base = build_name(movie['info'])
        new_base = unique_name(new_base, taken)
        taken.add(new_base)
        plan.append({'movie': movie, 'new_base': new_base})

    # ── Preview ─────────────────────────────────────────────────────
    print("\n" + "═" * 65)
    print("📋  ПЛАН ПЕРЕИМЕНОВАНИЯ")
    print("═" * 65)

    changed   = []
    unchanged = []

    for p in plan:
        m  = p['movie']
        nb = p['new_base']
        if m['type'] == 'in_folder' and m['folder'].name == nb:
            unchanged.append(p)
        else:
            changed.append(p)

    for p in changed:
        m  = p['movie']
        nb = p['new_base']

        if m['type'] == 'in_folder':
            print(f"\n  📁 {m['folder'].name}")
            print(f"     → 📁 {nb}/")
            if m['video']:
                print(f"        {m['video'].name}")
                print(f"        → {nb}{m['video'].suffix}")
            print(f"        {m['nfo'].name}")
            print(f"        → {nb}.nfo")
        else:
            vname = m['video'].name if m['video'] else '(видео не найдено!)'
            print(f"\n  📄 {vname}  [без папки]")
            print(f"     → создать 📁 {nb}/")
            if m['video']:
                print(f"        → {nb}{m['video'].suffix}")
            print(f"        {m['nfo'].name} → {nb}.nfo")
            for kind, f in find_related_files(base_dir, m['nfo'].stem):
                art_dest = f.name[len(m['nfo'].stem) + 1:] if kind == 'move_as_is' else nb + f.suffix
                print(f"        {f.name} → {art_dest}")

    print(f"\n{'═'*65}")
    print(f"  Изменений: {len(changed)}  |  Без изменений: {len(unchanged)}")
    print(f"{'═'*65}\n")

    if not apply:
        print("⚠️  Режим PREVIEW — файлы не изменены.")
        print("    Для применения запустите с флагом --apply\n")
        return

    # ── Применение ──────────────────────────────────────────────────
    confirm = input("Применить все изменения? [да/нет]: ").strip().lower()
    if confirm not in ('да', 'y', 'yes', 'д'):
        print("Отменено.")
        return

    log_path = base_dir / f"rename_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    errors   = []

    with open(log_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Тип', 'Старое', 'Новое', 'Статус'])

        for p in changed:
            m  = p['movie']
            nb = p['new_base']
            new_folder = base_dir / nb

            try:
                if m['type'] == 'in_folder':
                    _apply_in_folder(m, nb, base_dir, writer)
                else:
                    _apply_no_folder(m, nb, base_dir, writer)

                nfo_new = new_folder / f"{nb}.nfo"
                if nfo_new.exists():
                    patch_nfo(nfo_new)
                    writer.writerow(['nfo-patch', nfo_new.name, 'lockedfields обновлён', 'OK'])

                print(f"  ✅ {nb}")

            except Exception as e:
                errors.append(f"{m['nfo']}: {e}")
                writer.writerow(['ERROR', str(m['nfo']), nb, str(e)])
                print(f"  ❌ {nb}: {e}")

        # Патчим NFO у неизменённых фильмов
        for p in unchanged:
            try:
                patch_nfo(p['movie']['nfo'])
            except Exception:
                pass

    print(f"\n✅ Готово! Лог сохранён: {log_path}")
    if errors:
        print(f"\n❌ Ошибки ({len(errors)}):")
        for e in errors:
            print(f"   {e}")


# ═══════════════════════════════════════════════════════════════════
# Применение изменений
# ═══════════════════════════════════════════════════════════════════

def _apply_in_folder(m, nb, base_dir, writer):
    old_folder = m['folder']
    new_folder = base_dir / nb

    for f in list(old_folder.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if f.name.lower() in ART_NAMES:
            continue  # арт не переименовываем
        elif ext in VIDEO_EXTENSIONS or ext in RENAME_WITH_MOVIE:
            new_name = nb + f.suffix
            f.rename(old_folder / new_name)
            writer.writerow(['файл', f.name, new_name, 'OK'])

    old_folder.rename(new_folder)
    writer.writerow(['папка', old_folder.name, nb, 'OK'])


def _apply_no_folder(m, nb, base_dir, writer):
    new_folder = base_dir / nb
    new_folder.mkdir(exist_ok=True)
    old_stem = m['nfo'].stem

    if m['video']:
        dest = new_folder / (nb + m['video'].suffix)
        m['video'].rename(dest)
        writer.writerow(['видео', m['video'].name, dest.name, 'OK'])

    dest_nfo = new_folder / (nb + '.nfo')
    m['nfo'].rename(dest_nfo)
    writer.writerow(['nfo', m['nfo'].name, dest_nfo.name, 'OK'])

    for kind, f in find_related_files(base_dir, old_stem):
        if kind == 'rename':
            dest = new_folder / (nb + f.suffix)
        else:
            art_name = f.name[len(old_stem) + 1:]
            dest = new_folder / art_name
        f.rename(dest)
        writer.writerow([kind, f.name, dest.name, 'OK'])


# ═══════════════════════════════════════════════════════════════════
# Точка входа
# ═══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.is_dir():
        print(f"Ошибка: папка не найдена: {target}")
        sys.exit(1)

    do_apply = '--apply' in sys.argv

    print(f"📂 Папка:  {target}")
    print(f"🔧 Режим:  {'ПРИМЕНИТЬ' if do_apply else 'PREVIEW (файлы не изменяются)'}")

    process(target, do_apply)
