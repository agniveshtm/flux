from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from threading import Event
from typing import Callable


@dataclass
class ConversionResult:
    output_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class UnsupportedFormatError(ValueError):
    pass


def normalize_format(value: str) -> str:
    normalized = str(value).strip().lower().lstrip(".")
    if normalized == "jpeg":
        return "jpg"
    return normalized


class BaseConverter(ABC):
    @property
    @abstractmethod
    def supported_input_formats(self) -> list[str]:
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_output_formats(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def convert(
        self,
        input_paths: list[str],
        output_dir: str,
        target_format: str,
        options: dict,
        progress_cb: Callable[[int, int], None],
        cancel_event: Event,
    ) -> ConversionResult:
        raise NotImplementedError


class ConverterRegistry:
    def __init__(self) -> None:
        self._converters: dict[str, BaseConverter] = {}

    def register(self, converter: BaseConverter) -> BaseConverter:
        if not isinstance(converter, BaseConverter):
            raise TypeError("converter must implement BaseConverter")

        for output_format in converter.supported_output_formats:
            normalized = normalize_format(output_format)
            existing = self._converters.get(normalized)
            if existing is not None and existing is not converter:
                raise ValueError(f"Converter already registered for format: {normalized}")
            self._converters[normalized] = converter

        return converter

    register_converter = register

    def get_converter_for_format(self, target_format: str) -> BaseConverter:
        normalized = normalize_format(target_format)
        try:
            return self._converters[normalized]
        except KeyError as exc:
            raise UnsupportedFormatError(f"Unsupported output format: {target_format}") from exc

    def get_converter(self, target_format: str) -> BaseConverter:
        return self.get_converter_for_format(target_format)

    @property
    def supported_input_formats(self) -> list[str]:
        formats = {
            normalize_format(item)
            for converter in self._converters.values()
            for item in converter.supported_input_formats
        }
        return sorted(formats)

    @property
    def supported_output_formats(self) -> list[str]:
        return sorted(self._converters)