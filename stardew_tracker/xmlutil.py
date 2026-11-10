"""Мини-обёртки над ``xml.etree.ElementTree`` без зависимости от namespaces.

Сейвы Stardew Valley — обычный XML, но namespace-префиксы в них встречаются
непоследовательно. Все помощники сравнивают локальное имя тега/атрибута.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # nosec B405 - DOCTYPE/ENTITY блокируются в parse_xml
from collections.abc import Iterable, Iterator, Sequence

_INT_RE = re.compile(r"^-?\d+$")
_LEADING_INT_RE = re.compile(r"^(\d+)\s")

# DOCTYPE/ENTITY не нужны валидному сейву и открывают billion-laughs / XXE.
# defusedxml недоступен (проект принципиально без зависимостей), поэтому
# запрещаем опасные директивы до разбора. ElementTree не разворачивает
# внешние сущности, но внутренние — может.
_UNSAFE_XML_RE = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)


def has_unsafe_xml_directives(data: bytes) -> bool:
    """True, если документ содержит DOCTYPE/ENTITY-объявления."""

    return bool(_UNSAFE_XML_RE.search(data))


def parse_xml(data: bytes) -> ET.Element:
    """Разбирает XML, отклоняя DOCTYPE/ENTITY-бомбы.

    ``xml.etree`` бросает ``ET.ParseError`` на некорректном XML; вызывающая
    сторона превращает его в дружелюбную ошибку сейва.
    """

    if has_unsafe_xml_directives(data):
        raise ET.ParseError("XML-документ содержит запрещённые DOCTYPE/ENTITY-директивы")
    return ET.fromstring(data)  # nosec B314 - после проверки has_unsafe_xml_directives


def ln(el: ET.Element | None) -> str:
    """Локальное имя тега (без namespace)."""

    if el is None or not isinstance(el.tag, str):
        return ""
    return el.tag.rsplit("}", 1)[-1]


def lattr(el: ET.Element, name: str) -> str | None:
    """Значение атрибута по локальному имени."""

    for key, value in el.attrib.items():
        if key.rsplit("}", 1)[-1] == name or ":" + name in key:
            return value
    return None


def kid(el: ET.Element | None, name: str) -> ET.Element | None:
    """Первый прямой дочерний элемент с именем ``name``."""

    if el is None:
        return None
    for child in el:
        if ln(child) == name:
            return child
    return None


def kid_all(el: ET.Element | None, name: str) -> list[ET.Element]:
    """Все прямые дочерние элементы с именем ``name``."""

    return [] if el is None else [child for child in el if ln(child) == name]


def txt(el: ET.Element | None) -> str:
    """Текст элемента без пробелов по краям."""

    return (el.text or "").strip() if el is not None else ""


def deep(el: ET.Element | None, name: str, limit: int | None = None) -> ET.Element | None:
    """Первое вхождение тега на любой глубине (необязательный лимит обхода)."""

    if el is None:
        return None
    for index, sub in enumerate(el.iter(), start=1):
        if limit and index > limit:
            break
        if ln(sub) == name:
            return sub
    return None


def deep_text(el: ET.Element | None, name: str, default: str = "") -> str:
    return txt(deep(el, name)) or default


def first_int(el: ET.Element | None) -> int | None:
    """Первое целое внутри элемента (для ``int`` и ``ArrayOfInt > int``)."""

    if el is None:
        return None
    for sub in el.iter():
        text = (sub.text or "").strip()
        if not text:
            continue
        if _INT_RE.match(text):
            return int(text)
        match = _LEADING_INT_RE.match(text)
        if match:
            return int(match.group(1))
    return None


def bools(el: ET.Element | None) -> list[bool]:
    """Все ``<boolean>`` внутри элемента в порядке документа."""

    out: list[bool] = []
    for sub in el.iter() if el is not None else []:
        if ln(sub) == "boolean":
            out.append((sub.text or "").strip().lower() == "true")
    return out


def dict_pairs(el: ET.Element | None) -> list[tuple[str, ET.Element | None]]:
    """C#-словарь -> список ``(ключ, value)`` без потери порядка."""

    out: list[tuple[str, ET.Element | None]] = []
    if el is None:
        return out
    for item in el:
        if ln(item) != "item":
            continue
        key_el = kid(item, "key")
        value_el = kid(item, "value")
        key = ""
        if key_el is not None:
            for sub in key_el.iter():
                text = (sub.text or "").strip()
                if ln(sub) != "key" and text:
                    key = text
                    break
        out.append((key, value_el))
    return out


def norm_id(raw: object) -> str:
    """``'(O)128'`` -> ``'128'``; ``'128'`` -> ``'128'``; прочее без изменений."""

    if raw is None:
        return ""
    value = str(raw).strip()
    if value.startswith("("):
        value = value.split(")", 1)[1]
    match = re.match(r"^-?\d+", value)
    return match.group(0) if match else value


def iter_texts(el: ET.Element | None) -> Iterator[str]:
    return (txt(sub) for sub in (el.iter() if el is not None else []))


def first_text(el: ET.Element | None, names: Sequence[str]) -> str:
    """Первый непустой текст среди прямых дочерних элементов с именами."""

    for name in names:
        value = txt(kid(el, name))
        if value:
            return value
    return ""


def bool_value(el: ET.Element | None, default: bool = False) -> bool:
    if el is None:
        return default
    return txt(el).lower() == "true"


def flatten(elements: Iterable[ET.Element]) -> Iterator[ET.Element]:
    for element in elements:
        yield element
        yield from element.iter()
