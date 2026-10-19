# ADR 0017: Access-pattern DynamoDB persistence without inner contract changes

Status: Implementation decision for requested Milestone 6B.

## Decision

Use one PK/SK table, sparse operational GSIs, strongly consistent evidence collections,
conditional revision writes, and transactional uniqueness guards. Reuse the infrastructure
snapshot codec without SQL coupling. Domain/Application ports stay unchanged. Boto3 is an
optional infrastructure dependency; Moto is an optional integration-test dependency.

## Consequences

No AWS resource is deployed. Immutable evidence duplication supports base-table histories.
Operational GSIs are eventually consistent; decisions reload authoritative snapshots.
Bounded snapshots and transactions fail explicitly when too large. Global index/catalog
partitions and full scored-index ranking are acceptable for bounded single-operator V1;
sharding, artifact offload and production capacity planning require later decisions.

## Alternatives

Relational table-per-model mapping would require scans/joins. Eventual GSI uniqueness checks
cannot safely claim submission/payment identities. Changing inner contracts or adding S3
merely to fit storage would exceed this milestone. See the access-pattern matrix and
validation limits in [DynamoDB persistence](../dynamodb-persistence.md).
