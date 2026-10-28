# AGENTS.md

## Directorio operativo de centros (buscador de la Consejería)

Una consulta **sin filtros** a los widgets del buscador devuelve el listado
completo del directorio en 2 peticiones. No hace falta, y no hay que
reimplementar, un scraping centro a centro para obtener presencia o campos
básicos:

- `get-todos-centros.jsp` (POST, `filtros` con todos los valores vacíos) →
  nombre, municipio, dirección, teléfono y correo de **todos** los centros.
- `get-centros.jsp` (POST, mismos filtros vacíos) → etapa, coordenadas y
  centro de destino de **todos** los centros.

Esto ya está implementado en `directory_index()`
(`scripts/directory_diff.py`) y es lo que compara presencia y esos campos
para el directorio completo en cada ejecución, sea cual sea el `--scope`.

Solo hace falta pedir la ficha individual
(`get-centro-detalle.jsp?codigo=XXXXXXXX`) para los campos que **únicamente**
aparecen ahí: CEP, EOEP, CER, zona de inspección, web, fax y concierto. Por
eso `directory_diff.py --scope candidates` limita el bucle lento
(código a código, con `--delay`) a los centros que merece la pena revisar en
detalle; la comparación de presencia y campos básicos ya cubre siempre el
directorio entero con solo esas 2 peticiones.

## Entorno y comprobaciones

- No hay venv en el repo y el `python3` del sistema no trae `requests`: crea uno
  e instala `requirements.txt` (y `requirements-dev.txt` para `ruff`).
- CI (`.github/workflows/ci.yml`) ejecuta `ruff check scripts tests`,
  `python -m unittest discover -s tests`, `scripts/validate_data.py` y
  `scripts/validate_artifacts.py`. **`ruff format` no se aplica**: el repo no está
  formateado con él, no lo pases.

## Artefactos generados

- `centros.csv` y `centros.json` son artefactos **commiteados**. Tras tocar
  `scripts/update_data.py` o cualquier CSV de `data/`, regenéralos con
  `python scripts/update_data.py` y commitea el resultado.
- `dist/` está en `.gitignore`: los informes de `directory_diff.py` y
  `check_boc.py` no se commitean.

## Corregir datos erróneos del dataset abierto

- Nunca edites `centros.csv`/`centros.json` a mano. Añade una fila a
  `data/centre_field_overrides.csv` (`Codigo,Campo,Valor,Fuente,FuenteURL`), con
  la ficha del directorio como procedencia, y regenera.
- Las tablas curadas de `data/` mandan sobre lo que publica el dataset. Si un
  campo sale mal en el catálogo, mira primero el **orden de resolución** del
  merge en `update_data.py`, no el dato: alguna rama puede estar devolviendo el
  valor de origen antes de consultar la tabla curada.
- Los CSV curados se leen con `utf-8-sig` y alguno tiene CRLF; en la shell,
  pásalos por `tr -d '\r'` antes de iterar sobre sus valores.
