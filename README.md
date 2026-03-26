# EMBY_movies
Скрипт переименования фильмов по NFO файлам для Emby (WINDOWS)
=================================================================

Логика именования:
  - Российский фильм (country содержит Россию/СССР, или title==originaltitle): "Название год"
  - Зарубежный: "OriginalTitle (Title) год"
  - При неоднозначности — спрашивает
  - Конфликт имён → добавляет (1), (2)...

Что переименовывается:
  - Папка фильма
  - Видеофайл внутри папки
  - NFO файл (+ обновляет lockedfields внутри)
  - Субтитры (.srt, .ass и т.д.) с тем же базовым именем
  - Для фильмов без папки — создаётся папка, файлы переносятся

Что НЕ переименовывается (только перемещается в папку):
  - poster.jpg, fanart*.jpg, landscape.jpg, clearlogo.png и т.д.

Запуск:
  python D:\Python\PythonProject\rename_movies\rename_movies.py "D:\Media\Movies"            # preview
 
  python D:\Python\PythonProject\rename_movies\rename_movies.py "D:\Media\Movies" --apply    # применить (перед применением желательно остановить Emby, чтоб файлы не блокировались.)
