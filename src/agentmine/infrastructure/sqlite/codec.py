"""Versioned JSON snapshots for trusted local storage; never pickle or dynamic imports."""

import json
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from types import UnionType
from typing import Any, TypeVar, get_args, get_origin, get_type_hints
from zoneinfo import ZoneInfo

from agentmine.application.contracts import ai, opportunities, records, submission, workflow
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain import (
    budget,
    economics,
    eligibility,
    finance,
    money,
    opportunity,
    scoring,
    spending,
    values,
    work,
)


class SnapshotCodec:
    """Only explicitly imported model modules are allowed to supply snapshot types."""

    def __init__(self) -> None:
        modules = (
            ai,
            opportunities,
            records,
            submission,
            workflow,
            budget,
            economics,
            eligibility,
            finance,
            money,
            opportunity,
            scoring,
            spending,
            values,
            work,
        )
        self._types: dict[str, type[Any]] = {
            f"{module.__name__}.{name}": candidate
            for module in modules
            for name, candidate in vars(module).items()
            if isinstance(candidate, type)
            and candidate.__module__ == module.__name__
            and (is_dataclass(candidate) or issubclass(candidate, Enum))
        }

    def dumps(self, value: object) -> str:
        try:
            return json.dumps(
                {"version": 1, "value": self._encode(value)},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError, AttributeError) as error:
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "serialize", "Invalid snapshot"
            ) from error

    def loads[T](self, payload: str, expected: type[T]) -> T:
        try:
            envelope = json.loads(payload)
            if not isinstance(envelope, dict) or set(envelope) != {"version", "value"}:
                raise ValueError("Invalid envelope")
            if type(envelope["version"]) is not int or envelope["version"] != 1:
                raise PortError(
                    PortErrorCode.UNSUPPORTED, "deserialize", "Unknown snapshot version"
                )
            result = self._decode(envelope["value"])
            if not isinstance(result, expected):
                raise ValueError("Wrong snapshot type")
            return result
        except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as error:
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "deserialize", "Invalid snapshot"
            ) from error

    def _encode(self, value: object) -> object:
        if isinstance(value, Enum):
            return {"enum": self._tag(type(value)), "value": value.value}
        if value is None or type(value) in (str, int, bool):
            return value
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("Nonfinite decimal")
            return {"decimal": str(value)}
        if isinstance(value, datetime):
            return {
                "datetime": value.isoformat(),
                "fold": value.fold,
                "zone": value.tzinfo.key if isinstance(value.tzinfo, ZoneInfo) else None,
            }
        if isinstance(value, ZoneInfo):
            return {"zoneinfo": value.key}
        if isinstance(value, timezone):
            offset = value.utcoffset(None)
            assert offset is not None
            return {"timezone": self._encode(offset), "name": value.tzname(None)}
        if isinstance(value, timedelta):
            return {"timedelta": [value.days, value.seconds, value.microseconds]}
        if isinstance(value, (tuple, frozenset)):
            items = [self._encode(item) for item in value]
            if isinstance(value, frozenset):
                items.sort(key=lambda item: json.dumps(item, sort_keys=True))
            return {"tuple" if isinstance(value, tuple) else "frozenset": items}
        if is_dataclass(value) and not isinstance(value, type):
            return {
                "type": self._tag(type(value)),
                "fields": {
                    field.name: self._encode(getattr(value, field.name)) for field in fields(value)
                },
            }
        raise TypeError("Unsupported snapshot value")

    def _tag(self, cls: type[object]) -> str:
        tag = f"{cls.__module__}.{cls.__name__}"
        if self._types.get(tag) is not cls:
            raise TypeError("Unregistered snapshot type")
        return tag

    def _decode(self, node: Any) -> Any:
        # Any is confined to the JSON boundary; model fields and repository return types
        # are checked before a reconstructed object crosses the adapter boundary.
        if node is None or type(node) in (str, int, bool):
            return node
        if not isinstance(node, dict):
            raise ValueError("Tagged value required")
        keys = set(node)
        if keys == {"decimal"}:
            result = Decimal(node["decimal"])
            if not result.is_finite():
                raise ValueError("Nonfinite decimal")
            return result
        if keys == {"datetime", "fold", "zone"}:
            instant = datetime.fromisoformat(node["datetime"])
            if node["zone"] is not None:
                instant = instant.astimezone(ZoneInfo(node["zone"]))
            return instant.replace(fold=node["fold"])
        if keys == {"zoneinfo"}:
            return ZoneInfo(node["zoneinfo"])
        if keys == {"timezone", "name"}:
            return timezone(self._decode(node["timezone"]), node["name"])
        if keys == {"timedelta"}:
            return timedelta(*node["timedelta"])
        if keys in ({"tuple"}, {"frozenset"}):
            tag = next(iter(keys))
            items = (self._decode(item) for item in node[tag])
            return tuple(items) if tag == "tuple" else frozenset(items)
        if keys == {"enum", "value"}:
            cls = self._types[node["enum"]]
            if not issubclass(cls, Enum):
                raise ValueError("Enum required")
            return cls(node["value"])
        if keys != {"type", "fields"}:
            raise ValueError("Unknown snapshot tag")
        cls = self._types[node["type"]]
        if not is_dataclass(cls):
            raise ValueError("Dataclass required")
        definitions = fields(cls)
        if set(node["fields"]) != {field.name for field in definitions}:
            raise ValueError("Snapshot field mismatch")
        decoded = {name: self._decode(value) for name, value in node["fields"].items()}
        hints = get_type_hints(cls)
        if any(
            not _matches(decoded[name], hint) for name, hint in hints.items() if name in decoded
        ):
            raise ValueError("Snapshot field type mismatch")
        instance = cls(**{field.name: decoded[field.name] for field in definitions if field.init})
        for field in definitions:
            if field.init:
                continue
            if cls in (opportunity.Opportunity, budget.Budget, work.Task):
                # These are persisted aggregate state, not constructor defaults.
                object.__setattr__(instance, field.name, decoded[field.name])
            elif getattr(instance, field.name) != decoded[field.name]:
                raise ValueError("Derived calculation mismatch")
        if isinstance(instance, opportunity.Opportunity):
            history = instance.history
            if (
                not history
                or history[0] != opportunity.OpportunityState.DISCOVERED
                or history[-1] != instance.state
                or any(
                    after not in before.successors
                    for before, after in zip(history, history[1:], strict=False)
                )
            ):
                raise ValueError("Invalid lifecycle history")
        return instance


def _matches(value: object, hint: Any) -> bool:
    if isinstance(hint, TypeVar):
        return True  # AIResponse.result is checked as DeliverableDraft by its repository.
    origin = get_origin(hint)
    args = get_args(hint)
    if origin is UnionType:
        return any(_matches(value, item) for item in args)
    if origin in (tuple, frozenset):
        if not isinstance(value, origin):
            return False
        return all(_matches(item, args[0]) for item in value)
    if hint in (int, str, bool):
        return type(value) is hint
    return isinstance(value, origin or hint)
