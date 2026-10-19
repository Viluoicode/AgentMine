"""DynamoDB wire boundary, conditional writes and strongly read item collections."""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from agentmine.application.contracts.records import Versioned
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.infrastructure.snapshots import SnapshotCodec

# Any is confined to the SDK wire boundary; all stored application values pass the codec.
type Wire = dict[str, Any]
type Item = dict[str, str | int]


class DynamoClient(Protocol):
    def get_item(self, **kwargs: Any) -> Wire: ...
    def query(self, **kwargs: Any) -> Wire: ...
    def transact_write_items(self, **kwargs: Any) -> Wire: ...


def identity(*parts: str | int) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


def composite_key(*parts: str | int) -> str:
    return json.dumps(parts, separators=(",", ":"))


def key(kind: str, identifier: str) -> tuple[str, str]:
    return kind + "#" + identity(identifier), "META"


def collection(kind: str, parent: str) -> str:
    return "COLL#" + kind + "#" + identity(parent)


def timestamp(at: datetime) -> str:
    if at.utcoffset() is None:
        raise ValueError("Aware timestamp required")
    return at.astimezone(UTC).isoformat(timespec="microseconds")


def wire(item: Item) -> Wire:
    return {
        name: {"N": str(value)} if isinstance(value, int) else {"S": value}
        for name, value in item.items()
    }


def unwire(item: Wire) -> Item:
    try:
        return {
            name: int(value["N"]) if "N" in value else str(value["S"])
            for name, value in item.items()
        }
    except (ValueError, KeyError, TypeError):
        raise PortError(
            PortErrorCode.INVALID_RESPONSE, "dynamodb", "Invalid item attributes"
        ) from None


def conflict() -> PortError:
    return PortError(PortErrorCode.CONFLICT, "dynamodb", "Conditional persistence conflict")


@dataclass(frozen=True)
class IndexValues:
    parent: str | None = None
    occurred_at: datetime | None = None


class DynamoStore:
    def __init__(self, client: DynamoClient, table: str, *, page_size: int = 100) -> None:
        if not table.strip() or not 1 <= page_size <= 1000:
            raise ValueError("Explicit table and bounded page size required")
        self.client, self.table, self.page_size = client, table, page_size
        self.codec = SnapshotCodec()

    def _call(self, operation: str, arguments: Wire) -> Wire:
        try:
            if operation == "get":
                return self.client.get_item(**arguments)
            if operation == "query":
                return self.client.query(**arguments)
            return self.client.transact_write_items(**arguments)
        except Exception as error:
            response = getattr(error, "response", {})
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            reasons = response.get("CancellationReasons", []) if isinstance(response, dict) else []
            if code == "ConditionalCheckFailedException" or (
                code == "TransactionCanceledException"
                and any(
                    item.get("Code") in ("ConditionalCheckFailed", "TransactionConflict")
                    for item in reasons
                )
            ):
                raise conflict() from None
            logging.getLogger(__name__).error(
                "Persistence request failed", extra={"operation": operation}
            )
            # Do not leak SDK message, payloads, credentials, or pretend a failed read is absence.
            failure = (
                PortErrorCode.OUTCOME_UNKNOWN if operation == "write" else PortErrorCode.UNAVAILABLE
            )
            raise PortError(
                failure, "dynamodb", "Persistence request failed; reconcile writes by identity"
            ) from None

    def raw(self, pk: str, sk: str) -> Item | None:
        response = self._call(
            "get",
            {"TableName": self.table, "Key": wire({"PK": pk, "SK": sk}), "ConsistentRead": True},
        )
        return None if "Item" not in response else unwire(response["Item"])

    def item(self, pk: str, sk: str, value: object, revision: int = 1) -> Item:
        payload = self.codec.dumps(value)
        return {
            "PK": pk,
            "SK": sk,
            "payload": payload,
            "digest": hashlib.sha256(payload.encode()).hexdigest(),
            "revision": revision,
        }

    def decode[T](self, item: Item, expected: type[T]) -> Versioned[T]:
        payload, revision = item.get("payload"), item.get("revision")
        if (
            not isinstance(payload, str)
            or type(revision) is not int
            or revision < 1
            or hashlib.sha256(payload.encode()).hexdigest() != item.get("digest")
        ):
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "dynamodb", "Invalid snapshot or checksum"
            )
        return Versioned(self.codec.loads(payload, expected), revision)

    def get[T](self, kind: str, identifier: str, expected: type[T]) -> Versioned[T] | None:
        item = self.raw(*key(kind, identifier))
        return None if item is None else self.decode(item, expected)

    def value[T](self, kind: str, identifier: str, expected: type[T]) -> T | None:
        found = self.get(kind, identifier, expected)
        return None if found is None else found.value

    def put(self, item: Item, *, revision: int | None = None, identical: bool = False) -> Wire:
        condition = "attribute_not_exists(PK)"
        values: Item = {}
        if revision is not None:
            condition = "revision = :revision"
            values[":revision"] = revision
        elif identical:
            condition += " OR digest = :digest"
            values[":digest"] = item["digest"]
        body: Wire = {"TableName": self.table, "Item": wire(item), "ConditionExpression": condition}
        if values:
            body["ExpressionAttributeValues"] = wire(values)
        return {"Put": body}

    def transact(self, actions: list[Wire]) -> None:
        size = 0
        for action in actions:
            item = action.get("Put", {}).get("Item", {})
            for name, value in item.items():
                limit = 2048 if name.endswith("PK") else 1024 if name.endswith("SK") else None
                if limit is not None and len(value["S"].encode("utf-8")) > limit:
                    raise PortError(
                        PortErrorCode.UNSUPPORTED, "dynamodb", "Index key exceeds supported length"
                    )
            length = sum(
                len(name.encode()) + len(str(next(iter(value.values()))).encode())
                for name, value in item.items()
            )
            if length > 380 * 1024:
                raise PortError(
                    PortErrorCode.UNSUPPORTED, "dynamodb", "Snapshot exceeds supported item size"
                )
            size += length
        if not 1 <= len(actions) <= 100 or size > 3800 * 1024:
            raise PortError(
                PortErrorCode.UNSUPPORTED,
                "dynamodb",
                "Atomic write exceeds supported transaction size",
            )
        self._call("write", {"TransactItems": actions, "ClientRequestToken": str(uuid4())})

    def evidence(
        self, kind: str, identifier: str, value: object, indexes: IndexValues | None = None
    ) -> list[Item]:
        items = [self.item(*key(kind, identifier), value)]
        if indexes is not None and indexes.parent is not None:
            order = "" if indexes.occurred_at is None else timestamp(indexes.occurred_at)
            items.append(
                self.item(
                    collection(kind, indexes.parent), order + "#" + identity(identifier), value
                )
            )
        return items

    def immutable(
        self, kind: str, identifier: str, value: object, indexes: IndexValues | None = None
    ) -> bool:
        items = self.evidence(kind, identifier, value, indexes)
        try:
            self.transact([self.put(item) for item in items])
            return True
        except PortError as error:
            if error.code != PortErrorCode.CONFLICT:
                raise
            old = self.value(kind, identifier, type(value))
            if old != value:
                raise conflict() from None
            return False

    def query(
        self, pk: str, *, index: str | None = None, start: str | None = None, end: str | None = None
    ) -> tuple[Item, ...]:
        p, s = ("PK", "SK") if index is None else (index + "PK", index + "SK")
        expression = "#p = :p"
        values: Item = {":p": pk}
        names = {"#p": p}
        if start is not None and end is not None:
            expression += " AND #s BETWEEN :start AND :end"
            names["#s"] = s
            values.update({":start": start, ":end": end})
        args: Wire = {
            "TableName": self.table,
            "KeyConditionExpression": expression,
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": wire(values),
            "ConsistentRead": index is None,
            "Limit": self.page_size,
        }
        if index is not None:
            args["IndexName"] = index
        result: list[Item] = []
        while True:
            response = self._call("query", args)
            result.extend(unwire(item) for item in response.get("Items", []))
            cursor = response.get("LastEvaluatedKey")
            if not cursor:
                return tuple(result)
            args["ExclusiveStartKey"] = cursor

    def find[T](self, kind: str, expected: type[T], *, parent: str) -> tuple[Versioned[T], ...]:
        return tuple(self.decode(item, expected) for item in self.query(collection(kind, parent)))


def table_definition(name: str) -> Wire:
    """Return schema only. Resource creation belongs to explicit test/deployment tooling."""
    attributes = ["PK", "SK", *(f"GSI{i}{suffix}" for i in range(1, 4) for suffix in ("PK", "SK"))]
    return {
        "TableName": name,
        "BillingMode": "PAY_PER_REQUEST",
        "AttributeDefinitions": [
            {"AttributeName": attr, "AttributeType": "S"} for attr in attributes
        ],
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": f"GSI{i}",
                "KeySchema": [
                    {"AttributeName": f"GSI{i}PK", "KeyType": "HASH"},
                    {"AttributeName": f"GSI{i}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "KEYS_ONLY"},
            }
            for i in range(1, 4)
        ],
    }
