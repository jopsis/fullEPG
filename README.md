# fullEPG

Guía XMLTV con los **últimos ocho días** de programación, que es lo que casi
ninguna guía trae.

Las guías XMLTV corrientes miran hacia delante: publican hoy y los próximos
días, y del pasado dejan poco o nada. Medido sobre una guía pública muy usada,
la víspera aparecía con 33 canales frente a los 578 del día en curso. Eso basta
para ver qué echan esta tarde, pero no para elegir un programa de anteayer y
verlo en diferido.

Este repositorio recompone ese pasado a partir del catálogo público de
reposición de un operador, y lo publica como un XMLTV normal que cualquier
reproductor entiende.

## Dónde está

| Fichero | URL |
| --- | --- |
| Guía comprimida (recomendada) | https://jopsis.github.io/fullEPG/guia.xml.gz |
| Guía sin comprimir | https://jopsis.github.io/fullEPG/guia.xml |
| Cifras de la última generación | https://jopsis.github.io/fullEPG/estado.json |

Se regenera sola dos veces al día, a las 04:23 y a las 16:23 UTC. Son horas en
punto raras a propósito: el planificador de GitHub encola las tareas y, cuando
hay cola, retrasa o descarta las de los minutos más disputados.

El resultado de cada pasada queda anotado en
[`estado.json`](estado.json), en la raíz de este repositorio: cuándo se ejecutó,
si fue bien y las cifras de la guía que salió. Ese commit cumple además una
segunda función, que GitHub **desactiva los workflows programados cuando un
repositorio lleva 60 días sin actividad**, y este no recibe otros commits.

## Qué trae

Alrededor de 140 canales y 29 000 programas, desde ocho días atrás hasta unos
cuantos hacia delante. Pesa unos 700 KB comprimida.

De cada programa: inicio, fin, título, título del episodio, género,
calificación por edad y numeración de temporada/episodio cuando el origen la
da. Nada más, a propósito: lo que descarga el conversor son más de 300 MB de
los que el 58 % son metadatos comerciales que no pinta nada en una guía.

Cada canal declara su nombre y las variantes de calidad corrientes
(`HD`, `FHD`, `UHD`), porque los reproductores suelen emparejar por nombre
cuando el `tvg-id` no cuadra, y así encuentran su programación más canales.

## Aviso

Solo hay datos de programación: títulos, horarios y géneros. No contiene
enlaces de reproducción, credenciales ni claves, y no da acceso a ningún
contenido. Reponer un programa exige una suscripción con el operador
correspondiente.

El origen es una API pública sin documentar. Puede cambiar o dejar de estar
disponible sin aviso; si eso pasa, la acción fallará y la guía se quedará en la
última versión buena.

## Generarla a mano

```sh
python3 tools/build_epg.py --out public
```

Sin dependencias, solo biblioteca estándar. Tarda unos dos minutos. Con
`--limit N` se queda en los N primeros canales, que es lo cómodo para probar.
