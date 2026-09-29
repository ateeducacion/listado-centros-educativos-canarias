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
